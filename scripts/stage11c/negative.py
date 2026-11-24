"""Solver-interface counterexamples and fail-closed tests on private copies of actual captures."""
import argparse,array,copy,hashlib,json,shutil,struct,subprocess,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent/'stage11b'))
from theory import Graph,derive,parse,verify,Refused,need
from boolean import Proof,Formula,replay_dag
from audit import read,save,collect,audit_theory,rebound,rup_results,digest,LIMIT_BYTES

def ops(path):
    a=array.array('I');a.frombytes(path.read_bytes())
    if sys.byteorder!='little':a.byteswap()
    i=0;out=[]
    while i<len(a):
        k=a[i];i+=1
        if k in (0xfffffff0,0xfffffff3):n=a[i];i+=1
        else:n={0xfffffff1:3,0xfffffff2:0,0xfffffff4:2}[k]
        out.append((k,list(a[i:i+n])));i+=n
    return out
def put_ops(path,rows):
    a=array.array('I')
    for k,data in rows:
        a.append(k)
        if k in (0xfffffff0,0xfffffff3):a.append(len(data))
        a.extend(data)
    if sys.byteorder!='little':a.byteswap()
    path.write_bytes(a.tobytes())
def worker(exe,mode,dirs,out,extra=None):
    import os
    rd,wr=os.pipe()
    payload=b''
    for i,d in enumerate(dirs):
        payload+=(str(d)+'\n').encode()
        if i and extra:payload+=extra.encode()+b'\n'
    with (out/'stdout').open('wb') as so,(out/'stderr').open('wb') as se:
        try:
            p=subprocess.run([str(exe),mode],input=payload,stdout=so,stderr=se,pass_fds=(wr,),
                env=dict(PATH=os.environ['PATH'],LC_ALL='C',S10_PROTOCOL_FD=str(wr)),timeout=45)
        finally:os.close(wr)
    result=os.read(rd,65536).decode();os.close(rd);return p.returncode,result
def run(formal,out,baseline,release,co):
    out.mkdir(parents=True,exist_ok=True)
    source=formal/'fib_updates_8/1/TC/old';lock=formal/'lock12/1/TC/old'
    lib=read(source/'library.json.gz');old=Graph(source);f=Formula(source/'s8-input.bin')
    identity={i:2*i for i in range(f.n)};names={v:k for k,v in old.uid.items()}
    theory=next(t for t in lib['theories'].values() if t['origin']=='self_cycle' and
                {'po','rf'}<={n[0] for n in t['proof']} and any(n[0] in ('co','fr') for n in t['proof']))
    mapping=list(theory['old_clause']);assert audit_theory(old,old,theory,identity)
    result=[];saved={};original_rows=ops(source/'s8-input.bin')
    def directory(k):
        d=out/k;d.mkdir(exist_ok=True);(d/'worker').mkdir(exist_ok=True);(d/'plan.txt').write_text('old\n');return d
    def cold(key,graph=None,rows=None):
        if key in saved:return saved[key]
        d=directory(key)
        if graph is None:shutil.copyfile(source/'s8-graph.tsv',d/'s8-graph.tsv')
        else:(d/'s8-graph.tsv').write_text(''.join('\t'.join(map(str,r))+'\n' for r in graph))
        if rows is None:shutil.copyfile(source/'s8-input.bin',d/'s8-input.bin')
        else:put_ops(d/'s8-input.bin',rows)
        rc,protocol=worker(baseline,'F',[d],d);need(rc==0,'independent cold worker failed '+key)
        ans=(d/'answer.txt').read_text().split()
        saved[key]=dict(run=key,independent='unmodified stage-11B cold native worker',sat=ans[0]=='0',code=int(ans[0]),
                        answer_sha256=digest(d/'answer.txt'),stream=digest(d/'s8-input.bin'),graph=digest(d/'s8-graph.tsv'),protocol=protocol)
        return saved[key]
    frozen=cold('unchanged')
    def refuse(k,where,fn,ref):
        try:fn()
        except (Refused,ValueError,KeyError,IndexError,subprocess.TimeoutExpired) as e:
            result.append(dict(test=k,at=where,reason=type(e).__name__+': '+str(e),approved=0,cold=ref));return
        raise RuntimeError('uncertified test accepted: '+k)
    def graph_rows():return [s.split('\t') for s in (source/'s8-graph.tsv').read_text().splitlines()]
    def changed_graph(k,change):
        rows=graph_rows();g=copy.deepcopy(old);g.signatures.clear();change(g,rows)
        refuse(k,'audit_theory / checked premises',lambda:audit_theory(old,g,theory,identity),cold(k,rows))
    edge=next((r[1],r[2]) for r in theory['proof'] if r[0]=='po')
    def remove(g,rows):
        g.po.remove(edge);rows.remove(next(r for r in rows if r[:4]==['edge',names[edge[0]],names[edge[1]],'po']))
    changed_graph('01_deleted_PO',remove)
    def atomic(g,rows):
        remove(g,rows);rows.append(['edge',names[edge[0]],names[edge[1]],'apo',-1]);g.apo.add(edge)
    changed_graph('02_PO_to_APO',atomic)
    rf=next((r[1],r[2]) for r in theory['proof'] if r[0]=='rf');x=old.rf[rf]
    def reverse(g,rows):
        g.rf[rf]=x^1
        for r in rows:
            if r[:4]==['edge',names[rf[0]],names[rf[1]],'rf']:r[4]=str(x^1)
    changed_graph('03_RF_sign_changed',reverse)
    guard=next(r[4][0] for r in theory['proof'] if r[0] in ('co','fr'))
    def off(g,rows):
        g.guards[guard]=-2
        for r in rows:
            if r[:2]==['guard',names[guard]]:r[2]='-2'
    changed_graph('04_guard_false',off)
    g=copy.deepcopy(old);g.signatures.clear();v=list(g.nodes[rf[0]]);v[2]='changed_access_type';g.nodes[rf[0]]=tuple(v)
    refuse('05_typed_alias_metadata','semantic signature (metadata fault with identical native query)',lambda:audit_theory(old,g,theory,identity),frozen)
    def competitor(g,rows):
        addr=g.nodes[rf[0]][1];g.domains[addr].append('new_competing_write')
        fresh=names[rf[0]].split('#')[0]+'#110011';rows.append(['guard',fresh,-1,110011])
    changed_graph('06_competitor_domain',competitor)
    captures,events,learn,_=parse(source/'worker/proof.log')
    ev=events[next(int(i) for i,t in lib['theories'].items() if t==theory)]
    need(derive(old,ev,captures)==theory['proof'],'CO mutation lacks a valid starting proof')
    subprocess.run([str(co),str(out/'co-directions.tsv')],check=True,stdout=subprocess.DEVNULL,timeout=25)
    co_lines=(out/'co-directions.tsv').read_text().splitlines()
    co_ref=dict(test='native addMissingCoClauses / fresh solver per assignment',observations=co_lines[:6])
    altered=copy.deepcopy(ev);altered['cause']='CO'
    refuse('07_dynamic_CO_direction','derive: dynamic CO definitions unsupported',lambda:derive(old,altered,captures),co_ref)
    node=next(row for row in lib['dag'] if row[0]=='input');j=node[3];deleted=[];pos=0
    for k,data in original_rows:
        if k==0xfffffff0:
            pos+=1
            if pos-1==j:continue
        deleted.append((k,data))
    f2=copy.copy(f);f2.clauses=list(f.clauses);f2.clauses[j]=()
    leaves={int(i):t['old_clause'] for i,t in lib['theories'].items()}
    refuse('08_boolean_leaf_deleted','replay_dag original input index and signed content',lambda:replay_dag(lib['dag'],f2,leaves),cold('deleted-original',rows=deleted))
    broken=copy.deepcopy(theory['proof']);mid=next(q for q in broken if q[3]);mid[3]=[len(broken)+1]
    refuse('09_theory_parent_missing','independent rule DAG',lambda:verify(old,theory['old_clause'],broken),frozen)
    forged=copy.deepcopy(lib['dag']);r=next(row for row in forged if row[0]=='resolve');r[3]^=1
    refuse('10a_changed_resolution_pivot','explicit signed resolution',lambda:replay_dag(forged,f,leaves),frozen)
    bad=copy.deepcopy(lib['dag']);bad[-1][1]=[]
    refuse('10b_tampered_learnt','exact clause at proof root',lambda:replay_dag(bad,f,leaves),frozen)
    ll=read(lock/'library.json.gz');_,_,lr,_=parse(lock/'worker/proof.log')
    ix=next(int(i) for i in ll['mixed'] if len(lr[int(i)]['L'])<len(lr[int(i)]['Q']))
    ltheory={int(k):v for k,v in ll['theories'].items()};lf=Formula(lock/'s8-input.bin')
    Proof(lf,ltheory,lr).uip(ix);mod=copy.deepcopy(lr);mod[ix]['Q']=tuple(mod[ix]['Q'])+(2*lf.n+2,)
    lockref=read(formal/'lock12/0/stock/old/receipt.json')
    refuse('10c_missing_minimization','native pre-minimization cut',lambda:Proof(lf,ltheory,mod).uip(ix),dict(native_exit=lockref['exit'],stream=lockref['stream']))
    # One consistent signed slot permutation applied throughout the abstract Boolean input and theory declarations.
    y=next(z for z in old.by_raw if z!=x//2)
    mp=identity.copy();mp[x//2]=2*y+1;mp[y]=2*(x//2)
    reb=lambda z:mp[z//2]^(z&1) if z>=0 else z
    def rawmap(rows):
        out=[]
        for k,data in rows:
            if k in (0xfffffff0,0xfffffff3):data=[reb(z) for z in data]
            if k==0xfffffff4:data=[mp[data[0]]//2,data[1]]
            out.append((k,data))
        return [a for a in out if a[0]==0xfffffff1]+[a for a in out if a[0]!=0xfffffff1]
    gr=graph_rows()
    for row in gr:
        if row[0] in ('edge','guard'):
            j=4 if row[0]=='edge' else 2;row[j]=str(reb(int(row[j])))
    moved=copy.deepcopy(old)
    moved.rf={k:reb(z) for k,z in old.rf.items()};moved.guards={k:reb(z) for k,z in old.guards.items()}
    moved.aliases={mp[i]//2:frozenset(a[:-1]+(a[-1]^(mp[i]&1),) for a in vals) for i,vals in old.aliases.items()}
    assert audit_theory(old,moved,theory,mp)==rebound(theory['old_clause'],mp)
    re=cold('permuted',gr,rawmap(original_rows));need(re['code']==frozen['code'],'signed permutation changed verdict')
    result.append(dict(test='11a_signed_slot_permutation',at='signed semantic bijection',approved_proof=True,submitted=0,cold=re))
    moved.aliases[mp[x//2]//2]=frozenset();refuse('11b_changed_alias','complete signed alias group',lambda:audit_theory(old,moved,theory,mp),re)
    # Two version transitions in one persistent audited TC worker, with no transferable learns.
    for i,flags in enumerate(((True,False),(False,True))):
        dirs=[];refs=[]
        for k,badroot in enumerate(flags):
            rs=[(0xfffffff1,[0,2,1]),(0xfffffff0,[0])]+([(0xfffffff0,[1])] if badroot else [])+[(0xfffffff2,[]),(0xfffffff3,[])]
            key=f'root-{i}-{k}';refs.append(cold(key,[],rs));src=out/key
            d=directory(key+'-epoch');dirs.append(d)
            for n in ('s8-input.bin','s8-graph.tsv'):shutil.copyfile(src/n,d/n)
            (d/'plan.txt').write_text(('keep' if k else 'old')+'\n0 0\n');(d/'approved.tsv').write_bytes(b'')
        d=dirs[1];receipt='C11v1 '+' '.join(digest(d/f) for f in ('s8-input.bin','s8-graph.tsv','approved.tsv'))
        rc,protocol=worker(release,'TC',dirs,d,receipt);need(rc==0,'persistent root boundary')
        observed=[int((z/'answer.txt').read_text().split()[0]) for z in dirs]
        need(observed==[q['code'] for q in refs],'incorrect epoch root')
        result.append(dict(test=('12_old_UNSAT_new_SAT','13_old_SAT_new_UNSAT')[i],at='native epoch and empty audited import',
                           actual=observed,protocol=protocol,cold=refs))
    result.append(dict(test='14_alternating_assumptions',at='native shared and independent fresh queries',cold=co_lines[6:]))
    fake=tuple(theory['old_clause'])+(2*f.n+2,)
    refuse('15_unbound_dynamic_variable','signed rebind',lambda:rebound(fake,identity),co_ref)
    with tempfile.TemporaryDirectory(dir=out) as td:
        tmp=Path(td);(tmp/'worker').mkdir()
        with (tmp/'worker/proof.log').open('wb') as fd:fd.truncate(LIMIT_BYTES+1)
        refuse('16a_proof_memory_input_limit','collect before parsing',lambda:collect(tmp,'C'),frozen)
    refuse('16b_real_RUP_timeout','P1 proof subprocess deadline',lambda:rup_results(release.with_name('rupcheck'),source/'s8-input.bin',{}, {1:(1,)},f,timeout=0),frozen)
    child=subprocess.run([sys.executable,'-c',
        "import resource,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from theory import parse;resource.setrlimit(resource.RLIMIT_AS,(32*1024**2,32*1024**2))\ntry:parse(Path(sys.argv[2]))\nexcept MemoryError: print('REFUSE_MEMORY_LIMIT');sys.exit(0)\nsys.exit(2)",
        str(HERE),str(formal/'ticket56-reviewed/1/C/old/worker/proof.log')],capture_output=True,text=True,timeout=10)
    need(child.returncode==0 and child.stdout.strip()=='REFUSE_MEMORY_LIMIT','OS memory cap did not reach proof refusal')
    ticket_ref=read(formal/'ticket56-reviewed/0/stock/old/receipt.json')
    result.append(dict(test='16e_OS_proof_memory_limit',at='32 MiB RLIMIT_AS in isolated proof parser',reason=child.stdout.strip(),
                       approved=0,cold=dict(native_exit=ticket_ref['exit'],stream=ticket_ref['stream'])))
    refuse('16c_incomplete_snapshot','missing live assignment record',lambda:derive(old,{k:v for k,v in ev.items() if k!='evaluation'},captures),frozen)
    # Change the on-disk import after issuing a receipt. The native worker must never return a P1 answer.
    pair=[]
    for side in ('old','new'):
        z=directory('sealed-'+side);pair.append(z)
        for n in ('s8-input.bin','s8-graph.tsv','plan.txt'):shutil.copyfile(dirs[0 if side=='old' else 1]/n,z/n)
        (z/'approved.tsv').write_bytes(b'')
    z=pair[1];sig='C11v1 '+' '.join(digest(z/n) for n in ('s8-input.bin','s8-graph.tsv','approved.tsv'))
    (z/'approved.tsv').write_bytes(b'c1 1 0\n');rc,protocol=worker(release,'TC',pair,z,sig)
    need(rc!=0 and not (z/'answer.txt').exists(),'tampered approval reached search')
    result.append(dict(test='16d_tampered_native_import',at='native private receipt',approved=0,worker_exit=rc,protocol=protocol,
                       reason=(z/'stderr').read_text().strip(),cold=refs[1]))
    save(out,'negative.json',result)
if __name__=='__main__':run(*[Path(a).resolve() for a in sys.argv[1:]])
