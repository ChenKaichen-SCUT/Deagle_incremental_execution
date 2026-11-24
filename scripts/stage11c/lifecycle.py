"""Non-timed count-only build and replay. Accept counts only with identical native search bytes."""
import json,os,shutil,subprocess,sys
from pathlib import Path
from audit import save,read,digest
def instrument(d):
    def edit(file,a,b):
        p=d/file;s=p.read_text();assert s.count(a)==1,a;p.write_text(s.replace(a,b))
    edit('trace.hpp','size_t theory_id=0,','size_t uip_count=0,learn_units=0,prop_clauses=0,prop_units=0,db_reduce=0,db_simplify=0,gcs=0,removed_learnts=0,removed_orig=0,final_calls=0;\n    size_t theory_id=0,')
    edit('ClosureSolver.cc','c11::state().start();','++c11::state().uip_count;c11::state().start();')
    edit('ClosureSolver.cc','uncheckedEnqueue(learnt_clause[0]);\n            }else','++c11::state().learn_units;uncheckedEnqueue(learnt_clause[0]);\n            }else')
    edit('ClosureSolver.cc','uncheckedEnqueue(learnt_clause[0]);\n            theory_propagation++;','++c11::state().prop_units;uncheckedEnqueue(learnt_clause[0]);\n            theory_propagation++;')
    edit('ClosureSolver.cc','c11::state().propagated(*this,cr,learnt_clause,decisionLevel());','++c11::state().prop_clauses;c11::state().propagated(*this,cr,learnt_clause,decisionLevel());')
    edit('Solver.cc','c11::state().drop(cr);','if(c11::state().running){if(ca[cr].learnt())++c11::state().removed_learnts;else ++c11::state().removed_orig;}c11::state().drop(cr);')
    edit('Solver.cc','c11::state().gc();','if(c11::state().running)++c11::state().gcs;c11::state().gc();')
    for fn,field in [('void Solver::reduceDB()','db_reduce'),('bool Solver::simplify()','db_simplify'),('void Solver::analyzeFinal(Lit p, vec<Lit>& out_conflict)','final_calls')]:
        edit('Solver.cc',fn+'\n{',fn+'\n{\n    if(c11::state().running)++c11::state().'+field+';')
    fields='uip_count learn_units prop_clauses prop_units db_reduce db_simplify gcs removed_learnts removed_orig final_calls'.split()
    edit('driver.cpp','metric(f,"sat_code",rc);','metric(f,"sat_code",rc);\n      '+''.join(f'metric(f,"lc_{k}",c11::state().{k});' for k in fields))
def replay(formal,audit,out):
    from negative import worker
    out.mkdir(parents=True,exist_ok=True);table={}
    for cf in sorted(formal.glob('*/1/*/pair.json')):
        case=cf.parents[2].name;mode=cf.parent.name;cap=cf.parent;dest=out/case/mode;dest.mkdir(parents=True,exist_ok=True)
        ds=[]
        for side in ('old','new'):
            s=cap/side;d=dest/side;d.mkdir(exist_ok=True);(d/'worker').mkdir(exist_ok=True);ds.append(d)
            for n in ('s8-input.bin','s8-graph.tsv','events.tsv','plan.txt','approved.tsv'):
                if (s/n).is_file():shutil.copyfile(s/n,d/n)
        receipt=None;d=ds[1]
        if mode in ('T','C','TC'):receipt='C11v1 '+' '.join(digest(d/n) for n in ('s8-input.bin','s8-graph.tsv','approved.tsv'))
        rc,protocol=worker(audit,mode,ds,dest,receipt);assert rc==0,(case,mode,(dest/'stderr').read_text()[-600:])
        proof={}
        for i,side in enumerate(('old','new')):
            s=cap/side;d=ds[i];observed=dict(l.split('\t') for l in (d/'worker/stats.tsv').read_text().splitlines())
            trace=digest(d/'worker/search.bin')
            assert trace==digest(s/'worker/search.bin')
            for sibling in formal.glob(case+'/*/'+mode+'/'+side+'/receipt.json'):
                rr=read(sibling);assert rr['search_trace']==trace and all(rr['counters'][k]==int(observed[k]) for k in ('decisions','conflicts','propagations','theory_propagations','theory_conflicts'))
            proof[side]=dict(search_sha256=trace,counts={k[3:]:int(v) for k,v in observed.items() if k.startswith('lc_')})
        table[case+'/'+mode]=proof
    save(out,'counts.json',dict(binary=digest(audit),rows=table))
if __name__=='__main__':
    if sys.argv[1]=='instrument':instrument(Path(sys.argv[2]))
    else:replay(*map(Path,sys.argv[2:]))
