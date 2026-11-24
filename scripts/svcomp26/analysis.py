"""Re-derive trial equality, full model dispatch, admissions, physical CRefs and conservative learning evidence."""
import argparse
import collections
import csv
import hashlib
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from config import ROOT,TASKS,folder
from oracle import interpret,metadata,read,save,sha
from stream import inspect,states
sys.path.insert(0,str(ROOT))
from incdeagle.model.repeat import phase_digest
from scripts.stage10.bind import registry,decide
from scripts.stage10.evidence import PHASES,trace,lines
from scripts.stage10.experiment import signed_stats

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()
def csvout(p,rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with p.open('w',newline='',encoding='utf8') as stream:
        w=csv.DictWriter(stream,fieldnames=keys,lineterminator='\n');w.writeheader();w.writerows(rows)
def multiset(graph):
    return collections.Counter(graph.read_text().splitlines())
def rup(cnf,clause):
    # Refute the negated candidate with Boolean unit propagation on P1 originals only.
    truth={x^1 for x in clause}
    if any(x^1 in truth for x in truth):return True
    while True:
        before=len(truth)
        for row in cnf:
            if any(x in truth for x in row):continue
            live=[x for x in row if x^1 not in truth]
            if not live:return True
            if len(live)==1:truth.add(live[0])
        if len(truth)==before:return False
def statesummary(d0,d1,s0,s1):
    regs=[]
    for d in (d0,d1):
        try:reg=registry(d,read(d/'command.json')['settings'])
        except (ValueError,KeyError,IndexError,OSError,RecursionError) as ex:reg={'error':str(ex)}
        regs.append(reg)
    old,new=regs;complete=all('groups' in v for v in regs)
    plan=decide(old,new) if complete else {'reason':'refuse_incomplete_registry','pairs':[]}
    identity={a for a,b in plan['pairs'] if a==b}
    stable_raw=sum(1 for k,v in old.get('groups',{}).items() if new.get('groups',{}).get(k)==v)
    candidates=[]
    for d in (d0,d1):candidates.append(inspect(d/'s8-input.bin',identity)[1] if identity else collections.Counter())
    counts=candidates[0]&candidates[1]
    graphs=[multiset(d/'s8-graph.tsv') for d in (d0,d1)]
    versions=[]
    for d,r,g in zip((d0,d1),regs,graphs):
        receipt=read(d/'receipt.json')
        versions.append(dict(variables=receipt['variables'],clauses=receipt['clauses'],queries=len(receipt['stream']['queries']),
            nodes=receipt['native'][0]['graph_nodes'],edge_guard_order=dict(collections.Counter(x.split('\t')[0] for x in g.elements())),
            graph_sha256=digest(d/'s8-graph.tsv'),semantic_graph_sha256=r.get('graph'),registered=len(r.get('groups',{})),
            registry_error=r.get('error'),postsolve_active_learnts=receipt['native'][-1]['learnts']))
    driver=read(s1/'receipt.json')['driver'];kept=lines(s1/'worker/retained.tsv')
    actual=driver.get('actually_reattached',0)
    assert len(kept)==actual
    originals={r[0]:tuple(r[1:]) for r in lines(s0/'worker/original-resident.tsv')}
    for ref,*lits in kept:
        assert ref in originals and originals[ref]==tuple(lits) and counts[tuple(lits)] and all(x//2 in identity for x in lits)
    if driver:
        srow=read(s1/'admission.json')
        assert srow['reason']==plan['reason'] and srow['pairs']==[list(p) for p in plan['pairs']]
        assert not any(driver[k] for k in ('new_learnts_before_input','new_root_assigns_before_input','new_graph_nodes_before_input'))
        assert driver['generation']==(1 if driver['admission']=='keep' else 2)
        if driver['generation']==1:assert driver['object']==read(s0/'receipt.json')['native'][-1]['object']
        else:assert actual==0 and driver['object']!=read(s0/'receipt.json')['native'][-1]['object']
    learn=dict(snapshot_available=False,active_at_end=read(s0/'receipt.json')['native'][-1]['learnts'],fully_bound=None,proved_p1_rup=None,actually_imported=0)
    seal=s0/'worker/learning.bin'
    if seal.exists():
        a=memoryview(seal.read_bytes()).cast('i');i=0;total=0;bound=[]
        while i<len(a):
            ref,n=a[i:i+2];assert ref>=0 and n>0;i+=2;t=tuple(a[i:i+n]);i+=n;total+=1
            if all(x//2 in identity for x in t):bound.append(t)
        assert i==len(a) and total==learn['active_at_end']
        proofs=0
        if bound:
            from scripts.stage10.evidence import read_stream
            _,cnf,_=read_stream(d1/'s8-input.bin')
            proofs=sum(rup(cnf,t) for t in bound)
        learn.update(snapshot_available=True,fully_bound=len(bound),proved_p1_rup=proofs)
    fallback=read(s1.parent/'refusal.json')['reason'] if (s1.parent/'refusal.json').is_file() else None
    return dict(versions=versions,raw_graph_record_removed=sum((graphs[0]-graphs[1]).values()),raw_graph_record_added=sum((graphs[1]-graphs[0]).values()),
        semantic_graph_equal=(old['graph']==new['graph']) if complete else None,matching_signed_groups_same_slot_before_graph_gate=stable_raw,
        semantic_admission=plan['reason'],admitted_stable_variables=len(identity),common_eligible_p1_original_submissions=sum(counts.values()),
        actual_disposition=driver.get('admission',fallback),physical_reattach=actual,learning=learn)
def audit_trial(loc,oracle,mode):
    rec=read(loc/'receipt.json');cmd=read(loc/'command.json')
    assert not any(k.startswith(('INCDEAGLE_S4','INCDEAGLE_S5')) for k in cmd['environment_keys'])
    actual,_=interpret(read(loc/'result.json'),rec['exit']);assert actual['classification']==oracle['classification'] and actual['property_rows']==oracle['property_rows']==rec['properties']
    ops={k:list(map(int,v)) for k,*v in (s.split() for s in (loc/'s8-native.tsv').read_text().splitlines())}
    assert rec['dispatch']==len(read(loc/'visits.json'))==ops['other_dispatch'][0] and rec['dispatch']>0
    assert all(ops[k][0]==0 for k in ('prefix_dispatch','rebind','prefix_symbols','irep_read','rf_replay')) and all(ops[k][0]>0 for k in ('front','sc','rf','po'))
    assert not (loc/'old_done.json').exists() and not (loc/'native-import.json').exists()
    assert {k:phase_digest(read(loc/(k+'.json'))) for k in PHASES}==rec['phases']
    native=loc/'worker' if rec['driver'] else loc
    assert states(native/'native-state.tsv')==rec['native']
    assert rec['search_sha256']==digest(native/'search.bin') and rec['graph_sha256']==digest(loc/'s8-graph.tsv') and rec['cnf_sha256']==digest(loc/'s8-input.bin')
    hashes,branches,conflicts=trace(native/'search.bin')
    # The frozen hook reopens search.bin with "wb" on every solve. Counters and
    # native-state.tsv cover every solve, the binary trace covers the last one.
    assert rec['native'][-1]['conflicts']-rec['native'][-2]['conflicts']==conflicts
    sums=rec['counters'];end=rec['native'][-1]
    return dict(source_sha256=rec['source_sha256'],result=actual['classification'],target_status=actual['property_rows'][actual['target']],full_dispatch=rec['dispatch'],
        variables=rec['variables'],clauses=rec['clauses'],queries=len(rec['stream']['queries']),cnf=rec['cnf_sha256'],graph=rec['graph_sha256'],
        search=hashes,trace_scope='last_native_query',trace_branches=branches,trace_conflicts=conflicts,**sums,solver_wall_ms=rec['timing']['model_to_result_ns']/1e6,pure_search_ms=rec['timing']['pure_search_ns']/1e6,
        program_wall_ms=rec['timing']['program_wall_ns']/1e6,solve_ms=rec['timing']['solve_ns']/1e6,peak_rss_kib=end['peak_rss_kib'],
        native_pid=end['pid'],native_object=end['object'],model_pid=rec['model_pid'],generation=rec['driver'].get('generation'),
        reattached=rec['driver'].get('actually_reattached',0),postsolve_learnts=end['learnts'])
def derive(root,out):
    out.mkdir(parents=True,exist_ok=True);summary={};samples=[];rounds=[];alloracles={};cycles={}
    for task in TASKS:
        p0=root/'P0'/task
        if not (p0/'receipt.json').exists():continue
        oc=read(p0/'receipt.json')
        if (p0/'result.json').exists() and oc.get('exit') in (0,10):
            new,_=interpret(read(p0/'result.json'),oc['exit']);oc.update(new)
        alloracles[task]={'P0':oc}
        if (root/'P0-target'/task/'receipt.json').exists():alloracles[task]['target_option_replay']=read(root/'P0-target'/task/'receipt.json')
        for roundno in (1,2):
            p=root/'rounds'/task/f'P{roundno}';model=p/'model.json'
            if not model.exists():continue
            m=read(model);c=read(p/'controller.json');o=root/'oracles'/task/f'P{roundno}';fun=root/'functional'/task/f'P{roundno}'
            if (o/'receipt.json').exists():
                oc=read(o/'receipt.json');new,_=interpret(read(o/'result.json'),oc['exit'])
                assert new['classification']==oc['classification'] and oc['input_sha256']==m['candidate_sha256']==digest(p/'candidate.i')
                alloracles[task][f'P{roundno}']=oc
            else:oc={}
            checks=read(fun/'receipt.json') if (fun/'receipt.json').exists() else {}
            rounds.append(dict(task=task,version=f'P{roundno}' if m['status']=='FROZEN' else None,generation_rounds=m.get('generations',1),
                submission_status=m['status'],calls=len(m['requests']),response_ids=[v.get('response_id') for v in m['requests']],gen_wall_s=c['wall_ns']/1e9,
                peak_estimate=m['estimated_usd']['peak'],off_peak_estimate=m['estimated_usd']['off_peak'],target=oc.get('classification'),
                function_checks=checks.get('passed'),protected_lines=m.get('protected_lexical_lines_equal'),outcome=(oc.get('classification')=='BOUNDED_PASS' and checks.get('passed') is True and m.get('protected_lexical_lines_equal') is True)))
        ai=[x for x in rounds if x['task']==task]
        if ai:
            native=sum(x.get('elapsed_ns',0) for x in alloracles[task].values())/1e9
            recheck=root/'preflight/recheck'/task/'receipt.json'
            if recheck.exists():native+=read(recheck)['elapsed_ns']/1e9
            generation=sum(x['gen_wall_s'] for x in ai)
            cycles[task]=dict(verification_active_s=native,ai_active_s=generation,total_active_s=native+generation)
    pairs=root/'pairs'
    for parent in sorted(pairs.glob('*/*')):
        task=parent.parent.name;old,new=parent.name.split('-');label=task+'/'+parent.name
        if not (parent/'1/S/complete.json').exists():raise ValueError('incomplete pair '+label)
        mech=statesummary(parent/'1/F/old',parent/'1/F/candidate',parent/'1/S/old',parent/'1/S/candidate')
        differences=[];group=[]
        for t in sorted(d for d in parent.iterdir() if d.is_dir()):
            trial={}
            for mode in ('F','S'):
                rr=read(t/mode/'complete.json')
                tab=[]
                for phase,tag in (('old',old),('candidate',new)):
                    row=audit_trial(t/mode/phase,alloracles[task][tag],mode)
                    assert row['source_sha256']==alloracles[task][tag]['input_sha256']
                    row.update(task=task,pair=parent.name,trial=int(t.name),mode=mode,phase=phase,route=rr['mode'])
                    samples.append(row);tab.append(row)
                trial[mode]=tab
            for f,s in zip(trial['F'],trial['S']):
                assert all(f[k]==s[k] for k in ('cnf','graph','source_sha256','result','target_status','full_dispatch','queries','variables','clauses'))
                assert read(t/'F'/f['phase']/'receipt.json')['phases']==read(t/'S'/s['phase']/'receipt.json')['phases']
            f,s=trial['F'][1],trial['S'][1];differences.append(s['solver_wall_ms']-f['solver_wall_ms']);group.append(trial)
        perf={}
        for mode in ('F','S'):
            rows=[g[mode][1] for g in group]
            perf[mode]={k:statistics.median(v[k] for v in rows) for k in ('solver_wall_ms','pure_search_ms','program_wall_ms','decisions','conflicts','propagations','peak_rss_kib')}
        summary[label]=dict(mechanism=mech,P1_performance=perf,paired_solver_ms=differences,paired_median_ms=statistics.median(differences),faster=sum(x<0 for x in differences))
    save(out/'local-properties.json',alloracles);save(out/'repair-outcomes.json',rounds);save(out/'cycles.json',cycles);save(out/'solver-summary.json',summary);csvout(out/'trials.csv',samples)
    print('audited',len(samples),'complete model runs and',len(summary),'adjacent pairs')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);a=p.parse_args();derive(a.root.resolve(),a.output.resolve())
