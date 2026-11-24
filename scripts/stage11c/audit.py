"""Construct proofs from a frozen, contemporaneous P0 trace, then independently check P1."""
import collections,gzip,hashlib,json,subprocess,time
from pathlib import Path
from theory import Graph,Refused,derive,verify,h,need,parse
from boolean import Formula,Proof,norm,resolve,replay_dag
if not __debug__:
    raise RuntimeError('stage 11C requires Python assertions to be enabled')
CLOCK=time.monotonic_ns
LIMIT_BYTES=80*1024*1024
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest() if hasattr(hashlib,'file_digest') else sha_stream(f)
def sha_stream(f):
    a=hashlib.sha256()
    for b in iter(lambda:f.read(1024*1024),b''):a.update(b)
    return a.hexdigest()
def save(d,p,data):
    raw=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode()
    if p.endswith('.gz'):raw=gzip.compress(raw,compresslevel=2,mtime=0)
    (d/p).write_bytes(raw)
def read(p):
    raw=p.read_bytes();return json.loads(gzip.decompress(raw) if p.suffix=='.gz' else raw)
def collect(d,mode):
    start=CLOCK();trace=d/'worker/proof.log';need(trace.stat().st_size<=LIMIT_BYTES,'proof_capture_size_limit')
    g=Graph(d);f=Formula(d/'s8-input.bin')
    ns,ev,learn,counts=parse(trace);theories={};classed={};begin=CLOCK()
    seen=collections.Counter()
    for i,e in ev.items():
        try:
            k=e['origin'];seen[k]+=1
            need(seen[k]<=(90 if k=='reverse_rf' else 100),'theory_proof_budget')
            p=derive(g,e,ns);sup=verify(g,e['clause'],p)
            need(tuple(e['evaluation'][2])==f.goals[0],'query_scope_mismatch')
            shares={a:g.signature(a) for a in sup}
            theories[i]=dict(old_clause=e['clause'],proof=p,support=shares,origin=k,trigger=e['cause'],
                             active_evaluation=e['evaluation'],endpoint=[ns[e['a']],ns[e['b']]])
            classed[i]='P0_PROVED'
        except (Refused,KeyError) as ex:classed[i]=str(ex)
    theory_end=CLOCK();dags=Proof(f,theories,learn);mixed={};decisions={}
    direct=[i for i,l in learn.items() if any(p[1].startswith('t') for p in l['A'])]
    ranked=sorted(direct,key=lambda i:(len(learn[i]['L']),i))
    for j,i in enumerate(ranked):
        try:
            need(j<180 and len(learn[i]['L'])<=40,'mixed_proof_budget')
            last=dags.uip(i);cone=dags.cone(last)
            leaves=sorted({dags.nodes[q][3] for q in cone if dags.nodes[q][0]=='theory'})
            need(leaves and any(dags.nodes[q][0]=='resolve' for q in cone) and any(dags.nodes[q][0]=='input' for q in cone),'not_a_mixed_boolean_theory_resolution')
            need(all(norm(learn[i]['L'])!=norm(theories[t]['old_clause']) for t in leaves),'same_as_theory_clause')
            mixed[i]=dict(old_clause=learn[i]['L'],root=last,theories=leaves);decisions[i]='P0_PROVED'
        except (Refused,KeyError,RecursionError) as ex:decisions[i]=str(ex) or 'proof_depth'
    for i in learn:
        if i not in decisions:decisions[i]='no_direct_recorded_theory_parent' if mode!='T' else 'theory_only_mode'
    ids=sorted({q for c in mixed.values() for q in dags.cone(c['root'])})
    renum={q:i for i,q in enumerate(ids)}
    nodes=[[k,c,[renum[j] for j in parents],x] for q in ids for k,c,parents,x in (dags.nodes[q],)]
    for c in mixed.values():c['root']=renum[c['root']]
    replay_dag(nodes,f,{i:t['old_clause'] for i,t in theories.items()})
    proof_end=CLOCK()
    doc=dict(schema='native-OC-CDCL/1',source=digest(d/'s8-input.bin'),graph=digest(d/'s8-graph.tsv'),
             capture=digest(trace),counts=counts,theory_decisions=classed,mixed_decisions=decisions,
             theories=theories,mixed=mixed,dag=nodes,query=f.goals)
    save(d,'library.json.gz',doc)
    stamp=digest(d/'library.json.gz');end=CLOCK()
    save(d,'capture-time.json',dict(read_context_ns=begin-start,theory_ns=theory_end-begin,cdcl_ns=proof_end-theory_end,
        persist_ns=end-proof_end,total_ns=end-start,library_bytes=(d/'library.json.gz').stat().st_size,seal=stamp))
    return stamp

def rebound(c,mapping):
    need(all(x//2 in mapping for x in c),'unbound_semantic_literal')
    return norm(tuple(mapping[x//2]^(x&1) for x in c))
def audit_theory(a,b,c,mapping):
    old=c['old_clause'];cur=rebound(old,mapping)
    for x in old:
        a_group=a.aliases.get(x//2);q=mapping[x//2];b_group=b.aliases.get(q//2)
        need(a_group and b_group and {(z[:-1]+(z[-1]^(q&1),)) for z in a_group}==set(b_group),'changed_signed_theory_alias')
    support=verify(a,old,c['proof'])
    need(set(c['support'])==support,'unsealed_theory_support')
    for k in support:
        need(k in b.nodes and c['support'][k]==a.signature(k)==b.signature(k),'changed_event_type_guard_atomic_or_competitor_domain')
    verify(b,cur,c['proof'])
    return cur

def rup_results(exe,stream,sub,targets,f,timeout=18):
    names=list(sub);rows=[]
    for i in names:rows.append(('T',i,sub[i]))
    for i,c in targets.items():rows.append(('Q',i,c))
    request=''.join(f'{t} {i} {len(c)} '+' '.join(map(str,c))+'\n' for t,i,c in rows)
    p=subprocess.run([str(exe),str(stream)],input=request,text=True,capture_output=True,timeout=timeout,check=True)
    out={}
    for line in p.stdout.splitlines():
        fields=line.split();i,mode,conf=map(int,fields[:3]);used=set()
        def leaf(j):
            if j<len(f.clauses):return f.clauses[j]
            name=names[j-len(f.clauses)];used.add(name);return sub[name]
        current=leaf(conf);steps=[]
        for entry in fields[3:]:
            lit,ref=map(int,entry.split(':'));current=resolve(current,leaf(ref),lit)
            steps.append([lit,ref,list(current)])
        need(set(current)<=set(targets[i]) and bool(used)==bool(mode),'independent_P1_RUP_check_failed')
        out[i]=dict(mode='theory_RUP' if used else 'boolean_RUP',conflict=conf,steps=steps,used=sorted(used),clause=targets[i])
    return out

def review(old,new,stamp,mode,exe):
    started=CLOCK();need(digest(old/'library.json.gz')==stamp,'damaged_library')
    doc=read(old/'library.json.gz');need(doc['schema']=='native-OC-CDCL/1','theory_contract')
    need(doc['source']==digest(old/'s8-input.bin') and doc['graph']==digest(old/'s8-graph.tsv') and doc['capture']==digest(old/'worker/proof.log'),'old_snapshot_changed')
    a,b=Graph(old),Graph(new);f=Formula(new/'s8-input.bin')
    lines=(new/'plan.txt').read_text().splitlines()
    mapping=dict(tuple(map(int,l.split())) for l in lines[1:])
    need(len(mapping)==len(lines)-1 and len({q//2 for q in mapping.values()})==len(mapping),'noninjective_signed_mapping')
    tdec={};cdec={};sub={};ts=[];cs=[];begin=CLOCK()
    for k,c in doc['theories'].items():
        i=int(k)
        try:
            q=audit_theory(a,b,c,mapping);sub[i]=q;tdec[i]='P1_PROVED'
            if c['origin']!='reverse_rf':ts.append(('t'+k,q))
        except (Refused,KeyError) as ex:tdec[i]=str(ex)
    root_checks={}
    if sub:
        request=''.join(f'{i} {len(q)} '+' '.join(map(str,q))+'\n' for i,q in sub.items())
        path=new/'native-contract.tsv'
        with (new/'native-contract.stdout').open('wb') as output:
            subprocess.run([str(exe.with_name('native-contract')),str(new),str(path)],input=request.encode(),
                           stdout=output,stderr=subprocess.STDOUT,timeout=18,check=True)
        for line in path.read_text().splitlines():
            i,rc,dec,conf,prop=map(int,line.split());root_checks[i]=[rc,dec,conf,prop]
        for i in list(sub):
            if i not in root_checks or root_checks[i][:2]!=[1,0]:
                tdec[i]='current_native_root_did_not_refute_negation';del sub[i]
        ts=[(tag,q) for tag,q in ts if int(tag[1:]) in sub]
    theory_end=CLOCK();targets={}
    for k,c in doc['mixed'].items():
        i=int(k)
        try:
            need(norm(doc['dag'][c['root']][1])==norm(c['old_clause']),'changed_mixed_conclusion')
            targets[i]=rebound(c['old_clause'],mapping)
        except (Refused,KeyError) as ex:cdec[i]=str(ex)
    proofs=rup_results(exe,new/'s8-input.bin',sub,targets,f) if targets else {}
    for i,q in targets.items():
        if i not in proofs:cdec[i]='P1_RUP_with_current_theory_unproved_or_work_limit'
        elif proofs[i]['mode']=='boolean_RUP':cdec[i]='P1_pure_Boolean_RUP_separate'
        else:cs.append(('c'+str(i),q));cdec[i]='P1_MIXED_PROVED'
    cdcl_end=CLOCK();chosen=[];seen=set()
    for tag,q in (ts if mode in ('T','TC') else [])+(cs if mode in ('C','TC') else []):
        if q not in seen:chosen.append((tag,q));seen.add(q)
    raw=''.join(f'{tag} {len(q)} '+' '.join(map(str,q))+'\n' for tag,q in chosen).encode()
    # These files are created inside the controller's single-owner run directory before the native bridge is released.
    save(new,'audit.json.gz',dict(source=doc['source'],candidate=digest(new/'s8-input.bin'),graph=digest(new/'s8-graph.tsv'),
        library=stamp,query=f.goals,theory_decisions=tdec,mixed_decisions=cdec,extra_order=list(sub),proofs=proofs,
        native_root_checks=root_checks,approved=chosen,approved_sha256=hashlib.sha256(raw).hexdigest()))
    (new/'approved.tsv').write_bytes(raw)
    end=CLOCK();save(new,'review-time.json',dict(seal_mapping_ns=begin-started,theory_ns=theory_end-begin,cdcl_ns=cdcl_end-theory_end,
        persistence_ns=end-cdcl_end,total_ns=end-started))
    return (digest(new/'s8-input.bin'),digest(new/'s8-graph.tsv'),hashlib.sha256(raw).hexdigest())
