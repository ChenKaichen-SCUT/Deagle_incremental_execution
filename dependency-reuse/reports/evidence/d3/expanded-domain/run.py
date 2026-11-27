"""Exercise retirement of an actual learned clause after a candidate write is added."""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import struct
import subprocess


def digest(f):
    return hashlib.sha256(f.read_bytes()).hexdigest()


def save(f,x):
    f.write_text(json.dumps(x,indent=2)+'\n')


def finite_models(h,z):
    events,writes,_,rep,_,po,_,_=h.semantics(z)
    for perm in itertools.permutations(events):
        pos={e:i for i,e in enumerate(perm)}
        if any(pos[a]>=pos[b] for a,b in po):continue
        for valuation in itertools.product((False,True),repeat=8):
            val=lambda i: valuation[abs(i)-1]!=(i<0)
            if not all(any(map(val,c)) for c in z['clauses']):continue
            if not all(pos[w]<pos[r] and not any(pos[w]<pos[t]<pos[r] for t in writes if t not in (w,r))
                       for kind,w,r,lit in z['edges'] if kind=='rf' and val(lit)):continue
            yield {'event_order':perm,'true_variables':[i+1 for i,t in enumerate(valuation) if t]}


def clause_holds(raw,model):
    return any(((v//2 in model['true_variables']) != bool(v&1)) for v in raw)


def native_results(binaries,d,z):
    d.mkdir()
    lines=['8',*(' '.join(map(str,e)) for e in z['edges']),*('B '+' '.join(map(str,c)) for c in z['clauses'])]
    (d/'spec').write_text('\n'.join(lines)+'\n')
    for role,exe in binaries.items():
        wd=d/role;wd.mkdir()
        with (wd/'stdout').open('w') as out,(wd/'stderr').open('w') as err:
            subprocess.run([exe,d/'spec',wd/'proof.bin'],cwd=wd,stdout=out,stderr=err,check=True,timeout=30)
    assert (d/'D3/event-names.tsv').read_bytes()==(d/'D1/event-names.tsv').read_bytes()


def subgraphs(proof,birth_ids):
    data=proof.read_bytes(); pos=12; sections=[]
    for size in (16,4,8,16,12,8,12,4,4,4,4,4):
        count=struct.unpack_from('<I',data,pos)[0];sections.append((pos+4,count));pos+=4+size*count
    n,l,e,inp=map(lambda t:t[0],sections[:4])
    seq={struct.unpack_from('<I',data,inp+i*16)[0]:i+1 for i in range(sections[3][1])}
    result={}
    for target in birth_ids:
        stack=[target];nodes={}
        while stack:
            i=stack.pop()
            if i in nodes:continue
            begin_l,begin_e=struct.unpack_from('<II',data,n+16*(i-1))
            end_l,end_e,kind,flags=struct.unpack_from('<IIII',data,n+16*i)
            parents=[struct.unpack_from('<Ii',data,e+8*j) for j in range(begin_e,end_e)]
            nodes[i]=dict(kind=kind,flags=flags,conclusion=struct.unpack_from('<'+'i'*(end_l-begin_l),data,l+4*begin_l),
                          parents=parents,boolean_input_ordinal=seq.get(i))
            stack.extend(p for p,_ in parents)
        result[target]=nodes
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('tree','checker','native','oracle','output'):p.add_argument(arg,type=Path)
    a=p.parse_args()
    a.tree,a.checker,a.native,a.oracle,a.output=[x.resolve() for x in (a.tree,a.checker,a.native,a.oracle,a.output)]
    a.output.mkdir(parents=True,exist_ok=False)
    spec=importlib.util.spec_from_file_location('harness',a.tree/'dependency-reuse/tests/d3/check.py')
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    W,R,X,V=h.W,h.R,h.X,h.V
    p0=h.benchmark('domain',[('rf',W,R,5),('rf',X,R,6),('po',R,W,0)])
    coverage=(5,6)
    p0['clauses']=[coverage,(1,2,-6),(1,-2,-6),(7,3),(7,-3),(4,3),(4,-3)]
    p1=h.altered(p0,'add-write')
    p1['clauses'][0]=(5,6,8)
    tools={'D1':a.oracle,'D3':a.native}
    for side,z in [('P0',p0),('P1',p1)]: native_results(tools,a.output/side,z)
    src=a.output/'P0'
    ns=[(int(i),s,int(addr)) for i,s,addr in (line.split() for line in (src/'D3/event-names.tsv').read_text().splitlines())]
    summary={}
    tables={}
    for label,tar in [('self',p0),('expanded',p1)]:
        out=a.output/label;out.mkdir()
        changed=h.make_inputs(out,p0,tar,ns)
        cmd=[a.checker,src/'D3/proof.bin',out/'inputs',out/'map',src/'D1/native-learns.tsv',out/'decl',out]
        r=subprocess.run(cmd,capture_output=True,text=True);(out/'stderr').write_text(r.stderr);r.check_returncode()
        rows=[list(map(int,l.split())) for l in (out/'learned.tsv').read_text().splitlines()]
        summary[label]={k:int(v) for k,v in (l.split() for l in (out/'metrics.tsv').read_text().splitlines())}
        summary[label]['complete_rf_domain_changed']=changed;tables[label]=rows
    all_paths=subgraphs(src/'D3/proof.bin',[r[0] for r in tables['self']])
    save(a.output/'supports.json',all_paths)
    kept={r[0] for r in tables['expanded'] if r[7]}
    retired={r[0] for r in tables['self'] if r[7]}-kept
    used={i for i,path in all_paths.items() if any(x['boolean_input_ordinal']==1 for x in path.values())}
    assert used==retired and retired and kept,(used,retired,kept)
    examples={}
    def conclusions(i):return all_paths[i][i]['conclusion']
    for side,z in [('P0',p0),('P1',p1)]:
        n=0
        for model in finite_models(h,z):
            n+=1
            assert all(clause_holds(conclusions(i),model) for i in (all_paths if side=='P0' else kept))
            if side=='P1' and not examples and 8 in model['true_variables']:
                false=[i for i in retired if not clause_holds(conclusions(i),model)]
                if false:examples=dict(model=model,falsified_retired_ids=false)
        assert n;summary[side+'_SC_models']=n
    assert examples and set(examples['falsified_retired_ids'])==retired
    summary.update(old_candidates=sorted(h.semantics(p0)[7][R]),new_candidates=sorted(h.semantics(p1)[7][R]),
                   old_coverage=coverage,new_coverage=p1['clauses'][0],retired=sorted(retired),retained=sorted(kept),counterexample=examples,
                   tool_sha256={k:digest(v) for k,v in dict(checker=a.checker,**tools).items()})
    save(a.output/'summary.json',summary)
    print('retired',retired,'retained',kept,examples)


if __name__=='__main__':main()
