"""Audit-only native export. Compare production search bytes, then exhibit two rooted PO paths per consumed order."""
import collections,gzip,hashlib,json,shutil,sys
from pathlib import Path
def instrument(header):
    text=header.read_text()
    anchor='        const auto &d=root.stats;'
    if text.count(anchor)!=1:raise ValueError('unexpected proof export context')
    addition='''        std::vector<std::string> labels(symbols.size());
        for(const auto &v:symbols)labels[v.second]=v.first;
        std::ofstream used(directory+"/worker/consumed.tsv");
        for(const auto &p:consumed)used<<labels[p.first]<<char(9)<<labels[p.second]<<char(10);
'''
    header.write_text(text.replace(anchor,addition+anchor))

def read_table(file):
    return [row.split('\t') for row in file.read_text().splitlines()]

def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()

def answer_parts(file):
    fields=file.read_text().split()
    rc,n=map(int,fields[:2])
    if rc==1:
        assert len(fields)==2
        return (rc,n,()),{},[]
    assert rc==0
    end=2+n
    count=int(fields[end])
    ranks=dict(zip(fields[end+1:end+1+2*count:2],map(int,fields[end+2:end+1+2*count:2])))
    order_at=end+1+2*count
    order=fields[order_at+1:]
    assert len(ranks)==count and len(order)==int(fields[order_at])
    return (rc,n,tuple(fields[2:end])),ranks,order

def phase_check(case,side,d):
    from witness import result
    baseline=case/'1/GS'/side
    frozen_names=('s8-input.bin','s8-graph.tsv','events.tsv','plan.txt','worker/search.bin','worker/closure.tsv')
    hashes={n:digest(d/n) for n in frozen_names}
    if any(h!=digest(baseline/n) for n,h in hashes.items()):
        raise ValueError('instrumented replay changed the frozen inputs, search or closure: '+str(baseline))
    answer=digest(d/'answer.txt')
    original=digest(baseline/'answer.txt')
    variants=collections.defaultdict(list)
    for sibling in sorted(case.glob('*/GS/'+side)):
        if not all(digest(sibling/n)==h for n,h in hashes.items()):
            continue
        variants[digest(sibling/'answer.txt')].append(sibling.relative_to(case).as_posix())
    if answer not in variants:
        raise ValueError('instrumented output did not occur in a matching measured GS run: '+str(baseline))
    value,rank,order=answer_parts(d/'answer.txt')
    original_value,original_rank,original_order=answer_parts(baseline/'answer.txt')
    assert value==original_value and rank==original_rank
    assert collections.Counter(order)==collections.Counter(original_order)
    differences=[dict(index=i,round1=x,audit=y,rank=rank[x])
                 for i,(x,y) in enumerate(zip(original_order,order)) if x!=y]
    assert all(rank[row['audit']]==row['rank'] for row in differences)
    strict=None
    if value[0]==0:
        measured=case/variants[answer][0]
        strict=result(measured)
        if strict['status']!='EXPLICIT_SC_ORDER':
            raise ValueError('measured SAT answer has no certified complete order')
        strict=dict(status=strict['status'],events=len(strict['order']))
    return dict(hashes=hashes,audit_answer=answer,round1_answer=original,
                measured_GS_variants=variants,complete_answer_matches=variants[answer],
                equal_boolean_assignment=True,equal_rank_map=True,within_rank_changes=differences,
                strict_witness=strict)

def predecessors(base):
    adj=collections.defaultdict(list);roots={}
    for a,b in sorted(base):adj[a].append(b)
    def path(a,b):
        if a not in roots:
            q=collections.deque([a]);parents={a:None}
            while q:
                p=q.popleft()
                for t in adj[p]:
                    if t not in parents:parents[t]=p;q.append(t)
            roots[a]=parents
        result=[b];parents=roots[a]
        while result[-1]!=a:result.append(parents[result[-1]])
        result.reverse()
        assert all(edge in base for edge in zip(result,result[1:]))
        return result
    return path
def replay(run,audit,out):
    from negative import run_worker,stats
    data={};meta={};out.mkdir(parents=True,exist_ok=True)
    for case in ('lock12','lock01','batch_retained','fib_updates_8','ticket56-reviewed'):
        src=run/'formal'/case/'1/GS';dest=audit/'proof-replay'/case;dest.mkdir(exist_ok=True,parents=True);dirs=[]
        for phase in ('old','new'):
            sd=src/phase;d=dest/phase;d.mkdir(exist_ok=True);(d/'worker').mkdir(exist_ok=True);dirs.append(d)
            for f in ('s8-input.bin','s8-graph.tsv','plan.txt','events.tsv'):shutil.copyfile(sd/f,d/f)
        code,protocol=run_worker(audit/'worker','GS',dirs,dest);assert code==0
        bases=[];clean=None;checks=[]
        for i,(side,d) in enumerate(zip(('old','new'),dirs)):
            checks.append(phase_check(run/'formal'/case,side,d))
            rows=read_table(d/'worker/closure.tsv')
            bases.append({(a,b) for a,b,base,kept in rows if base=='1'})
            if i==1:clean={(a,b) for a,b,base,kept in rows if kept=='1'}
        pairs=set(map(tuple,read_table(dirs[1]/'worker/consumed.tsv')))
        assert len(pairs)==int(stats(src/'new/worker/closure-stats.tsv')['used_derived'])
        assert pairs<=clean and not (pairs&bases[0])
        labels=sorted({k for group in bases for edge in group for k in edge})
        ids={a:i for i,a in enumerate(labels)};path0,path1=map(predecessors,bases)
        rs=[{'pair':[ids[a],ids[b]],'P0':[ids[n] for n in path0(a,b)],'P1':[ids[n] for n in path1(a,b)]} for a,b in sorted(pairs)]
        data[case]=dict(semantic_blocks=labels,direct_PO_quotient=[sorted([ids[a],ids[b]] for a,b in edges) for edges in bases],proofs=rs)
        meta[case]=dict(consumed=len(rs),replayed=checks,protocol=protocol)
    blob=(json.dumps(data,sort_keys=True,separators=(',',':'))+'\n').encode()
    (out/'proofs.json.gz').write_bytes(gzip.compress(blob,mtime=0))
    (out/'proof-replay.json').write_text(json.dumps({'audit_worker_sha256':digest(audit/'worker'),'proof_bytes_sha256':hashlib.sha256(blob).hexdigest(),'cases':meta},sort_keys=True,indent=2)+'\n')
if __name__=='__main__':
    if sys.argv[1]=='instrument':instrument(Path(sys.argv[2]))
    elif sys.argv[1]=='replay':replay(*map(Path,sys.argv[2:]))
