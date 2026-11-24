"""Read-only differences of two fully generated native models. Unbound literals remain unknown."""
from collections import Counter,defaultdict
from functools import lru_cache
import gzip
import json
import mmap
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path
from prepare import REPO,DS,E,dump,h
sys.path.insert(0,str(REPO))
from incdeagle.model.identity import digest
from scripts.stage11b.bindings import bind,signed_map,capture_identity


def load(p):return json.loads(p.read_bytes())


def number_terms(doc,root_id):
    pool=doc['ireps']
    refs={v for r in pool for k,v in r.get('named',{}).items() if k=='working_directory'}
    for r in pool:
        if refs.intersection(r.get('sub',[])) or any(k!='working_directory' and v in refs for k,v in r.get('named',{}).items()):
            raise ValueError('directory also appears in a semantic field')
    for v in refs:
        name=pool[v]['id']
        if pool[v]!={'id':name} or not name.endswith('/'+root_id):raise ValueError('unknown source-directory marker '+name)
    @lru_cache(None)
    def term(i):
        if i is None:return None
        r=pool[i]
        if i in refs:return digest(['capture-directory'])
        return digest([r['id'],[(k,term(v)) for k,v in sorted(r.get('named',{}).items())],[term(v) for v in r.get('sub',[])]])
    return term


def graph(d,receipt,certificates=True):
    m=load(d/'full_model.json');g=load(d/'goto.json');raw=load(d/'native-bindings.json');visits=load(d/'visits.json')
    if raw['site']!='bmc_util before save_raw_graph/init':raise ValueError('unexpected observation site')
    mt,gt=number_terms(m,d.name),number_terms(g,d.name)
    layout=digest(g['layout']);funcs=defaultdict(list);local={};counts=Counter()
    for r in g['instructions']:
        fn=r['function'];local[fn,r['pc']]=counts[fn];counts[fn]+=1
    def ordinal(r):return local[r['function'],r['pc']]
    for r in g['instructions']:
        fn=r['function']
        funcs[fn].append([ordinal(r),r['file'],r['line'],r['column'],r['kind'],[local[fn,n] for n in r.get('targets',[])],r.get('property'),gt(r.get('code')),gt(r.get('condition'))])
    functions={k:digest(v) for k,v in funcs.items()}
    @lru_cache(None)
    def prefix(fn,index): return digest(funcs[fn][:index+1])
    def frame_key(v):
        chain=[]
        for frame in v['frames']:
            caller=frame.get('caller');call=None
            if caller:
                fn=caller['function'];i=ordinal(caller);call=[fn,i,prefix(fn,i)]
            chain.append([frame['function'],frame['loops'],call])
        return [v['function'],ordinal(v),chain]
    threads={0:digest(['main',layout])};births=Counter()
    for b in m['thread_births']:
        # Later edits to main cannot change an earlier, byte-identical spawn
        # prefix. Include its actual typed instructions and dynamic occurrence.
        index=ordinal(b);fn=b['function']
        root=(threads[b['parent']],fn,prefix(fn,index),index,mt(b['guard']))
        births[root]+=1
        if b['child'] in threads:raise ValueError('duplicate spawn')
        threads[b['child']]=digest([root,births[root]])
    occ=Counter();names={};rows={};blocks=defaultdict(list)
    for s in m['steps']:
        ep=s.get('oc_name')
        if not ep:continue
        if ep in names:raise ValueError('ambiguous endpoint')
        vis=s['visit'];fr=None
        if vis:
            v=visits[vis-1]
            if v['thread']!=s['thread']:raise ValueError('bad visit')
            fr=frame_key(v)
        ty=mt(m['ireps'][s['lhs']].get('named',{}).get('type')) if s.get('lhs') is not None else None
        desc=[layout,threads[s['thread']],s['function'],functions[s['function']],ordinal(s),fr,s['kind'],s.get('object'),
              s.get('address_l1'),raw['addresses'][ep],ty,mt(s['guard'])]
        site=digest(desc);occ[site]+=1
        uid=digest([site,occ[site]])
        names[ep]=uid
        rows[ep]=dict(kind=s['kind'],object=s.get('object'),address=raw['addresses'][ep],type=ty,guard=mt(s['guard']),
                      function=s['function'],pc=s['pc'],static_site=site,occurrence=occ[site])
        if s['atomic_section']:blocks[s['atomic_section']].append(ep)
    assert names.keys()==raw['addresses'].keys() and len(set(names.values()))==len(names)
    current=next((r['id'] for r in g['ireps'] if isinstance(r.get('id'),str) and r['id'].endswith('/'+d.name)),None)
    source=next(iter(receipt['files'].values()))['sha256']
    review={};cert=False
    for file in (('lock-review.json','ticket-review.json') if certificates else ()):
        reg=load(REPO/'reports/evidence/stage-11b/versions'/file)
        rec=reg.get('versions',reg).get(source)
        if not rec or not current:continue
        flags=list(rec['argv'])
        if '--property' in flags:
            i=flags.index('--property');assert flags[i+1]=='reach_error.assertion.1'; del flags[i:i+2]
        if flags!=receipt['argv'] or receipt['properties']!=[['reach_error.assertion.1','SUCCESS' if receipt['result']=='UNSAT' else 'FAILURE']]:continue
        if all(capture_identity(k,(d/k).read_bytes(),current)==v for k,v in rec['hashes'].items()):
            assert set(rec['roles'])<=set(names)
            for ep,key in rec['roles'].items():names[ep]=digest([file,key])
            cert=file
            if file=='lock-review.json':review[source]={**rec,'argv':receipt['argv']}
    groups=None
    native_settings=dict(argv=receipt['argv'],binary=receipt['binary'],backend='Minisat::ClosureSolver/fixed/native-restricted')
    try:
        with tempfile.TemporaryDirectory() as tmp:
            norm=Path(tmp)
            for p in d.iterdir():
                if p.name in ('goto.json','full_model.json'):
                    doc=load(p);pool=doc['ireps']
                    refs={v for r in pool for k,v in r.get('named',{}).items() if k=='working_directory'}
                    for v in refs:
                        assert pool[v]=={'id':current}
                        pool[v]={'id':'<source-working-directory>'}
                    (norm/p.name).write_bytes(json.dumps(doc).encode())
                elif p.name in ('bits.tsv','s8-graph.tsv','visits.json','native-bindings.json','s8-input.bin','program.c','program.i'):
                    try:os.link(p,norm/p.name)
                    except OSError:shutil.copyfile(p,norm/p.name)
            _,legacy,_=bind(norm,native_settings,source,review,'<source-working-directory>')
            binding='function-relative typed subset, complete supported signed aliases'
            if cert=='lock-review.json':
                groups=legacy;binding='stage11b audited lock roles and complete signed groups'
    except (ValueError,KeyError,IndexError,TypeError,AssertionError) as exc:
        binding='typed subset with full supported signed aliases; stage11b refused: '+str(exc)
    edges=Counter();atoms=defaultdict(list);guards={};exprs={r['local_symbol']:r['guard'] for r in m['oc_guards']}
    strong={ep:digest([uid,*[rows[ep][k] for k in ('kind','type','address','guard')]]) for ep,uid in names.items()}
    for edge,ssa in zip(raw['edges'],m['oc_edges'],strict=True):
        assert all(edge[k]==ssa[k] for k in ('kind','from','to'))
        row=(edge['kind'],names[edge['from']],names[edge['to']]);edges[row]+=1
        if row[0]=='rf':
            x=edge['x'];assert x>=0
            atoms[x//2].append(('rf',digest(['rf',strong[edge['from']],strong[edge['to']]]),x&1))
    for guard in raw['guards']:
        ep=guard['event'];x=guard['x'];e=names[ep];ex=mt(exprs[ep]);guards[e]=(ex,'var' if x>=0 else x)
        if x>=0:atoms[x//2].append(('guard',digest([strong[ep],ex]),x&1))
    if groups is None:
        # Reuse stage 10's signed SSA definition keys even when an initialization
        # event with visit=0 prevents the all-or-nothing stage 11B graph freeze.
        # An unresolved scalar alias vetoes the entire SAT variable.
        assignments=defaultdict(list)
        for step in m['steps']:
            if step['kind']=='assignment' and step.get('local_symbol'):assignments[step['local_symbol']].append(step)
        denied=set()
        pcs={(r['function'],r['pc']):r for r in g['instructions']}
        for line in (d/'bits.tsv').read_text().splitlines():
            name,kind,width,*strings=line.split('\t')
            bits=list(map(int,strings));defs=assignments[name]
            if kind not in ('signedbv','unsignedbv') or not width.isdecimal() or len(bits)!=int(width) or len(defs)!=1 or not defs[0]['visit']:
                denied.update(x//2 for x in bits if x>=0);continue
            st=defs[0];v=visits[st['visit']-1];pc=pcs[st['function'],st['pc']]
            if v['thread']!=st['thread']:raise ValueError('bad SSA visit')
            identity=digest([layout,threads[st['thread']],name,kind,width,st['function'],functions[st['function']],ordinal(st),
                             [pc[k] for k in ('file','line','column','kind')],frame_key(v),
                             [mt(st.get(f)) for f in ('lhs','rhs','guard','original_lhs')]])
            for i,x in enumerate(bits):
                if x>=0:atoms[x//2].append(('scalar',digest([identity,i]),x&1))
        groups={};dups=set()
        for var,labels in atoms.items():
            if var in denied:continue
            labels=sorted(labels);sg=labels[0][-1]
            key=tuple((kind,label,s^sg) for kind,label,s in labels)
            if key in groups:dups.add(key)
            else:groups[key]=(var,sg)
        for key in dups:del groups[key]
    matched={uid:rows[ep] for ep,uid in names.items()}
    return dict(names=names,rows=matched,edges=edges,guards=guards,groups=groups,cert=cert,binding=binding,
                blocks=[set(names[v] for v in group) for group in blocks.values()])


def cnf(path,mapping):
    counts=Counter();goals=[];matched=Counter()
    with path.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
        a=memoryview(mm).cast('I');i=0
        if sys.byteorder!='little':raise RuntimeError('little-endian host required')
        try:
            while i<len(a):
                k=a[i];i+=1
                if k==0xfffffff1:
                    assert a[i]==counts['variables'];counts['variables']+=1;i+=3
                elif k==0xfffffff2:counts['graphs']+=1
                elif k==0xfffffff4:i+=2
                elif k in (0xfffffff0,0xfffffff3):
                    n=a[i];i+=1;assert i+n<=len(a)
                    if k==0xfffffff0:
                        counts['clauses']+=1
                        if n==0 or (a[i]//2 in mapping and all(a[j]//2 in mapping for j in range(i+1,i+n))):
                            matched[tuple(sorted(mapping[x//2]^(x&1) for x in a[i:i+n]))]+=1
                    else:goals.append(list(a[i:i+n]))
                    i+=n
                else:raise ValueError('unknown opcode')
            assert i==len(a) and counts['graphs']==1 and goals
        finally:a.release()
    return dict(counts,assumptions=goals),matched


def components(vertices,pairs):
    parent={v:v for v in vertices}
    def find(v):
        while v!=parent[v]:
            parent[v]=parent[parent[v]];v=parent[v]
        return v
    for a,b in pairs:parent[find(a)]=find(b)
    sets=defaultdict(set)
    for v in parent:sets[find(v)].add(v)
    return list(sets.values())


def blocks_diff(a,b,common):
    return dict(old_groups=len(a),new_groups=len(b),
                witnessed_splits=sum(sum(bool(x&y&common) for y in b)>1 for x in a),
                witnessed_merges=sum(sum(bool(x&y&common) for x in a)>1 for y in b),
                old_unmatched=sum(not x&common for x in a),new_unmatched=sum(not x&common for x in b))


def learned(d,receipt):
    p=d/'search.bin'
    if receipt['counters']['queries']!=1:return {'generated_uip':None,'reason':'trace is overwritten on successive solve calls'}
    raw=load(d/'native-bindings.json')
    roles=defaultdict(set)
    for edge in raw['edges']:
        if edge['kind']=='rf' and edge['x']>=0:roles[edge['x']//2].add(('rf',edge['x']&1))
    for guard in raw['guards']:
        if guard['x']>=0:roles[guard['x']//2].add(('guard',guard['x']&1))
    choices=Counter()
    size=p.stat().st_size
    with p.open('rb') as f:
        level_counts=Counter();dec=0
        while tag:=f.read(4):
            k,=struct.unpack('<i',tag)
            if k==1:
                _,literal=struct.unpack('<ii',f.read(8))
                for atom,sign in roles.get(literal//2,()):
                    choices[atom+('_true' if literal&1==sign else '_false')]+=1
                dec+=1
            elif k==2:
                level,n=struct.unpack('<ii',f.read(8))
                if n<0 or f.tell()+4*n>size:raise ValueError('bad reason length')
                f.seek(4*n,1);level_counts[level]+=1
            else:raise ValueError('unknown search tag')
    assert sum(level_counts.values())==receipt['counters']['conflicts']
    gen=sum(n for level,n in level_counts.items() if level>0)
    proofs=[]
    for key,row in load(REPO/'reports/evidence/stage-11c/lifecycle.json')['rows'].items():
        if not key.endswith('/F'):continue
        for side,v in row.items():
            if v['search_sha256']==receipt['raw_sha256']['search.bin']:
                assert gen==v['counts']['uip_count']
                proofs.append(dict(case=key,side=side,lifecycle=v['counts']))
    archived=[]
    if proofs:
        for row in load(REPO/'reports/evidence/stage-11c/trials.json'):
            if row['mode']!='TC' or row['trial']!=1:continue
            prev=row['sides'][0];hashes=receipt['raw_sha256']
            if (prev['stream'],prev['graph'],prev['search_trace'])!=(hashes['s8-input.bin'],hashes['s8-graph.tsv'],hashes['search.bin']):continue
            info=load(REPO/'reports/evidence/stage-11c/summary.json')[row['case']]['modes']['TC']['individual'][0]['reuse']
            archived.append(dict(case=row['case'],stage11c_commit='7d2d08ecbf6e643d3537131489ab6ba23c327c52',
                                 counts=info['p0'],theory=info['p0_theory'],mixed=info['p0_mixed']))
    return dict(generated_uip=gen,positive_level_conflicts=gen,root_conflicts=level_counts[0],decision_records=dec,rf_guard_decision_assignments=choices,
                live_learnts_end=receipt['counters']['learnt_live_end'],stage11c_cold_transcript_matches=proofs,previous_matching_p0_proof_inventory=archived)


def compare(old,new,r0,r1,details=None):
    a=graph(old,r0);b=graph(new,r1)
    if a['cert']!=b['cert']:
        # A reviewed identity convention must apply on both sides.
        if a['cert']:a=graph(old,r0,False)
        if b['cert']:b=graph(new,r1,False)
    sm=signed_map(a['groups'],b['groups']);ident={v//2:2*(v//2) for v in sm.values()}
    n0,c0=cnf(old/'s8-input.bin',sm);n1,c1=cnf(new/'s8-input.bin',ident)
    retained=(c0&c1).total();same=r0['raw_sha256']['s8-input.bin']==r1['raw_sha256']['s8-input.bin']
    boolean=dict(old=n0,new=n1,semantic_variables=len(sm),renumbered=sum(i!=v//2 for i,v in sm.items()),polarity_flips=sum(v&1 for v in sm.values()),
                 old_bound_alias_groups=len(a['groups']),new_bound_alias_groups=len(b['groups']),aliases_old_only=len(a['groups'].keys()-b['groups'].keys()),
                 aliases_new_only=len(b['groups'].keys()-a['groups'].keys()),original_retained_confirmed=retained,old_mapped_only=(c0-c1).total(),
                 new_mapped_only=(c1-c0).total(),old_unknown=n0['clauses']-c0.total(),new_unknown=n1['clauses']-c1.total(),
                 ordered_native_stream_identical=same,semantic_mapping=sorted(sm.items()),binding_methods=[a['binding'],b['binding']])
    x=a['rows'];y=b['rows'];common=x.keys()&y.keys()
    changes={}
    for k in sorted(set(e[0] for e in a['edges']+b['edges'])):
        l=Counter({e[1:]:v for e,v in a['edges'].items() if e[0]==k});r=Counter({e[1:]:v for e,v in b['edges'].items() if e[0]==k})
        changes[k]=dict(old=l.total(),new=r.total(),matched=(l&r).total(),old_only_confirmed=sum(v for (s,t),v in (l-r).items() if s in common and t in common),
                        new_only_confirmed=sum(v for (s,t),v in (r-l).items() if s in common and t in common))
    def aps(z):return components(z['rows'],[(s,t) for k,s,t in z['edges'] if k=='apo'])
    guards=a['guards'].keys()&b['guards'].keys()
    if details is not None:
        changeset=dict(old_events=x,new_events=y,old_only_edges=[[list(k),v] for k,v in sorted((a['edges']-b['edges']).items())],
            new_only_edges=[[list(k),v] for k,v in sorted((b['edges']-a['edges']).items())],old_guards=a['guards'],new_guards=b['guards'],
            old_blocks=[sorted(z) for z in a['blocks']],new_blocks=[sorted(z) for z in b['blocks']],
            mapped_old_only_clauses=[[list(k),v] for k,v in sorted((c0-c1).items())],mapped_new_only_clauses=[[list(k),v] for k,v in sorted((c1-c0).items())])
        details.write_bytes(gzip.compress(json.dumps(changeset,sort_keys=True,separators=(',',':')).encode(),mtime=0))
    addr=lambda z:Counter(v['address'] for v in z.values())
    theory=dict(old_events=len(x),new_events=len(y),matched_events=len(common),old_unresolved_events=len(x)-len(common),new_unresolved_events=len(y)-len(common),
        edges=changes,guards=dict(old=len(a['guards']),new=len(b['guards']),comparable=len(guards),changed=sum(a['guards'][v]!=b['guards'][v] for v in guards)),
        explicit_sections=blocks_diff(a['blocks'],b['blocks'],common),apo_components=blocks_diff(aps(a),aps(b),common),
        access=dict(old=Counter(z['kind'] for z in x.values()),new=Counter(z['kind'] for z in y.values()),matched_changes=sum(tuple(x[i][k] for k in ('kind','type','address'))!=tuple(y[i][k] for k in ('kind','type','address')) for i in common)),
        addresses=dict(old=addr(x),new=addr(y)),static_ws_co_rows=[sum(v for (k,s,t),v in z['edges'].items() if k in ('ws','co')) for z in (a,b)],
        dynamic_rf_guard_co_breakdown=None,dynamic_reason='cold counters aggregate theory propagation/cycles; no typed trail per enqueue; static APO/RF and address partitions are not activated orders',
        certificates=[a['cert'],b['cert']],event_maps=[a['names'],b['names']])
    t_changed=(len(x)!=len(y) or any(v['old']!=v['new'] or v['old_only_confirmed'] or v['new_only_confirmed'] for v in changes.values())
               or theory['guards']['changed'] or len(a['blocks'])!=len(b['blocks']))
    b_changed=n0['variables']!=n1['variables'] or n0['clauses']!=n1['clauses'] or boolean['old_mapped_only'] or boolean['new_mapped_only']
    cls='B_AND_T' if b_changed and t_changed else 'T_WITH_IDENTICAL_BOOLEAN_STREAM' if t_changed and same else 'B_CHANGED_T_UNRESOLVED' if b_changed else 'UNRESOLVED'
    return dict(classification=cls,logical_monotonicity='unproved',boolean=boolean,theory=theory,old_knowledge=learned(old,r0))
