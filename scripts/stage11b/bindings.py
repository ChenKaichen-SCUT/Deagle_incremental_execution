"""Build typed event identities and polarity-aware alias groups from this model."""
from pathlib import Path
from collections import defaultdict
from functools import lru_cache
import gzip, hashlib, json, sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import digest,read,file_sha
from incdeagle.theory.context import freeze
from scripts.stage10.bind import registry

def capture_identity(filename,blob,working_directory):
    if filename not in ('native-bindings.json','full_model.json','goto.json'):
        return hashlib.sha256(blob).hexdigest()
    doc=json.loads(blob)
    if filename=='native-bindings.json':
        if not isinstance(doc.pop('snapshot_ns'),int):raise ValueError('unknown timing field')
    else:
        pool=doc['ireps']
        refs={v for row in pool for k,v in row.get('named',{}).items() if k=='working_directory'}
        for row in pool:
            if refs.intersection(row.get('sub',[])) or any(v in refs and k!='working_directory' for k,v in row.get('named',{}).items()):
                raise ValueError('working directory used as a semantic value')
        for v in refs:
            if pool[v]!={'id':str(working_directory)}:raise ValueError('unrecognized source directory marker')
            pool[v]={'id':'<source-working-directory>'}
        if 'oc_guards' in doc:doc['oc_guards'].sort(key=lambda r:r['local_symbol'])
    return digest(doc)

def reviewed_records(root):
    sys.path.insert(0,str(root.resolve()/'scripts/stage11a'))
    from real import Archive
    archive=Archive(root)
    meta=json.loads(gzip.decompress((root/'reports/evidence/stage-11a/real-declarations.json.gz').read_bytes()))
    audit=read(root/'reports/evidence/stage-11a/real-delta.json')
    out={}
    for name,side in [('P1','old'),('P2','candidate')]:
        q=audit['frozen_queries'][side]
        prefix='pairs/read_write_lock-2/P1-P2/1/F/'+side+'/'
        files=('s8-input.bin','s8-graph.tsv','native-bindings.json','goto.json','visits.json','full_model.json')
        cwd='/root/Deagle_incremental_execution/runs/svcomp26/project/runs/svcomp26/work/read_write_lock-2'
        out[q['source_sha256']]=dict(argv=q['argv'],hashes={k:capture_identity(k,archive.get('F/'+side+'/'+k),cwd) for k in files},
            raw_evidence={k:audit['receipts'][prefix+k] for k in files},
            roles={v['endpoint']:k for k,v in meta[name]['events'].items()})
    return out

def bind(directory,settings,source,review,cwd):
    ctx,theory=freeze(directory,settings,{'context':settings})
    native=read(directory/'native-bindings.json')
    reg=registry(directory,settings)
    model=read(directory/'full_model.json')
    pool=model['ireps']
    @lru_cache(None)
    def expr(i):
        if i is None:return None
        node=pool[i]
        return digest([node['id'],[(k,expr(v)) for k,v in sorted(node.get('named',{}).items())],
                       [expr(v) for v in node.get('sub',[])]])
    uids={}
    def pair(name,uid):
        if uids.setdefault(name,uid)!=uid:raise ValueError('inconsistent endpoint')
    for e,t in zip(native['edges'],ctx['edges']):
        pair(e['from'],t['from']);pair(e['to'],t['to'])
    for t,raw,pos in theory.by_key.values():
        if t['kind']=='guard':pair(native['guards'][pos-len(native['edges'])]['event'],t['event'])
    if set(uids)!=set(native['addresses']):raise ValueError('uncovered endpoint')
    audit=review.get(source)
    if audit:
        if settings['argv']!=audit['argv'] or any(capture_identity(k,(directory/k).read_bytes(),cwd)!=v for k,v in audit['hashes'].items()):
            raise ValueError('frozen review capture mismatch')
        if set(audit['roles'])!=set(uids):raise ValueError('incomplete reviewed roles')
    names={}
    for name,uid in uids.items():
        row=ctx['events'][uid]
        anchor=['reviewed-lock',audit['roles'][name]] if audit else ['typed-site',row['identity'],ctx['threads']]
        names[name]=digest([anchor,ctx['layout'],*[row[k] for k in ('role','object','address_l1','type','event_guard','solver_address')]])
    if len(set(names.values()))!=len(names):raise ValueError('ambiguous semantics')
    groups=defaultdict(list)
    for raw,atoms in reg['groups'].items():
        for kind,label,sign in atoms:
            if kind=='scalar':groups[raw].append((kind,label,sign))
    declarations=set()
    for e,v in zip(native['edges'],model['oc_edges']):
        start,end=names[e['from']],names[e['to']]
        kind=e['kind']
        atom=(kind,start,end)
        if kind=='rf':
            raw=e['x'];groups[raw//2].append(('rf',digest(atom),raw&1))
        declarations.add((kind,start,end))
    guards={v['local_symbol']:v for v in model['oc_guards']}
    for g in native['guards']:
        raw=g['x'];name=g['event'];atom=(names[name],expr(guards[name]['guard']))
        if raw>=0:groups[raw//2].append(('guard',digest(atom),raw&1))
        declarations.add(('guard',*atom,raw if raw<0 else 'var'))
    declarations.update(('event',v) for v in names.values())
    for s in ctx['atomic_sections']:declarations.add(('explicit_section',*sorted(s)))
    aliases={}
    for var,group in groups.items():
        group=sorted(group);sign=group[0][-1]
        key=tuple((k,h,p^sign) for k,h,p in group)
        if key in aliases:raise ValueError('ambiguous signed alias group')
        aliases[key]=(var,sign)
        declarations.add(('binding',digest(key)))
    return names,aliases,declarations

def signed_map(old,new):
    result={}
    for k in old.keys()&new.keys():
        a,sg=old[k];b,tg=new[k]
        if a in result:raise ValueError('source noninjective')
        result[a]=2*b+(sg^tg)
    if len({v//2 for v in result.values()})!=len(result):raise ValueError('target noninjective')
    return result

def write_plan(d,names,mapping,reason):
    if names is not None:
        (d/'events.tsv').write_text(''.join(f'{k}\t{v}\n' for k,v in sorted(names.items())))
    (d/'plan.txt').write_text(reason+'\n'+''.join(f'{k} {v}\n' for k,v in sorted(mapping.items())))
