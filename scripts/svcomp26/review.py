"""Cross-check the released version files, official origins, AI denominator, graph and calendar records."""
import argparse
import collections
import csv
import difflib
import gzip
import json
import re
import statistics
import tarfile
from decimal import Decimal
from pathlib import Path
from config import ROOT,TASKS,folder
from oracle import metadata,read,save,sha
def review(raw,evidence):
    outcomes=read(evidence/'repair-outcomes.json');solvers=read(evidence/'solver-summary.json');props=read(evidence/'local-properties.json')
    official={r['task']:r for r in csv.DictReader((evidence/'candidates.csv').open(encoding='utf8'))}
    files=read(evidence/'original-files.json');machine=read(raw/'machine.json');cycle=read(evidence/'cycles.json');histories={};graphs={};identities={}
    for task in TASKS:
        group=TASKS[task][0];spec=folder(task)/(task+'.yml')
        assert sha(spec)==files[group+'/'+spec.name]
        src=folder(task)/(task+'.i');assert sha(src)==files[group+'/'+src.name]
        rows=[r for r in outcomes if r['task']==task]
        if not rows:continue
        assert official[group+'/'+task+'.yml']['official_score']=='1' and props[task]['P0']['classification']=='VIOLATION'
        assert sum(r['calls'] for r in rows)<=4 and sum(Decimal(r['peak_estimate']) for r in rows)<=Decimal('.14') and cycle[task]['ai_active_s']<=320
        hist=dict(official_cpu=official[group+'/'+task+'.yml']['cpu_s'],P0_s=props[task]['P0']['elapsed_ns']/1e9,
            budget_calls=4,actual_calls=sum(r['calls'] for r in rows),verification_s={},ai_s=[r['gen_wall_s'] for r in rows],calendar=machine['calendar'][task],active=cycle[task])
        for r in rows:
            v=r['version']
            if not v:continue
            pub=ROOT/'cases/svcomp26/versions'/task/v;model=read(raw/'rounds'/task/v/'model.json');in_repo=pub/'program.i'
            old=src if v=='P1' else pub.parent/'P1/program.i'
            assert sha(in_repo)==model['candidate_sha256']==sha(raw/'rounds'/task/v/'candidate.i')
            assert sha(old)==model['source_sha256'] and sha(pub/'repair.patch')==model['patch_sha256']
            patch=''.join(difflib.unified_diff(old.read_bytes().decode().splitlines(True),in_repo.read_bytes().decode().splitlines(True),fromfile='a/program.i',tofile='b/program.i'))
            assert patch.encode()==(pub/'repair.patch').read_bytes()
            hist['verification_s'][v]=props[task][v]['elapsed_ns']/1e9
            identities[task+'/'+v]=read(pub/'identity.json')
        histories[task]=hist
    for label,v in solvers.items():
        base=raw/'pairs'/label/'1/F';edge=[];summaries=[]
        for phase in ('old','candidate'):
            graph=(base/phase/'s8-graph.tsv').read_text().splitlines();rows=[r.split('\t') for r in graph]
            triples=collections.Counter((r[1],r[2],r[3]) for r in rows if r[0]=='edge');edge.append(triples)
            summaries.append(dict(kinds=dict(collections.Counter(k for a,b,k in triples.elements())),guards=sum(r[0]=='guard' for r in rows),
                           cnf_stream=sha(base/phase/'s8-input.bin'),graph=sha(base/phase/'s8-graph.tsv')))
        graphs[label]=dict(versions=summaries,endpoint_kind_records_removed=sum((edge[0]-edge[1]).values()),
             endpoint_kind_records_added=sum((edge[1]-edge[0]).values()),first_removed=list((edge[0]-edge[1]).elements())[:3],first_added=list((edge[1]-edge[0]).elements())[:3])
    for task,hist in histories.items():
        labels=[label for label in sorted(solvers) if label.split('/')[0]==task]
        if not labels:continue
        hist['cycle_with_instrumented_verification']={}
        for mode in ('F','S'):
            trials=[]
            for repeat in ('1','2','3'):
                legs=[raw/'pairs'/label/repeat/mode for label in labels]
                programs=sum(read(p/phase/'receipt.json')['timing']['program_wall_ns'] for p in legs for phase in ('old','candidate'))/1e9
                sessions=sum(read(p/'complete.json')['wall_ns'] for p in legs)/1e9
                trials.append(dict(instrumented_programs_s=programs,complete_session_with_capture_checks_s=sessions,
                    ai_plus_programs_s=cycle[task]['ai_active_s']+programs,
                    independent_checks_plus_ai_plus_complete_sessions_s=cycle[task]['total_active_s']+sessions))
            hist['cycle_with_instrumented_verification'][mode]={'trials':trials,'median_s':{k:statistics.median(x[k] for x in trials) for k in trials[0]}}
    tasks=set(histories);first=[r for r in outcomes if r['version']=='P1'];latest=[next(r for r in reversed(outcomes) if r['task']==t) for t in sorted(tasks)]
    totalcalls=sum(r['calls'] for r in outcomes)
    ids=[rid for r in outcomes for rid in r['response_ids']]
    assert len(set(ids))==len(ids)==totalcalls and None not in ids
    totals=dict(attempted_tasks=len(tasks),frozen_first_versions=len(first),frozen_versions=len(identities),api_responses=totalcalls,first_call_success=sum(r['calls']==1 and r['outcome'] for r in first),
        first_generation_success=sum(r['generation_rounds']==1 and r['outcome'] for r in first),first_frozen_version_success=sum(r['outcome'] for r in first),
        final_bounded_functional_success=sum(r['outcome'] for r in latest),P1_target_still_violated=sum(r['target']=='VIOLATION' for r in first),
        final_frozen_target_still_violated=sum(r['target']=='VIOLATION' for r in latest),all_frozen_residual=sum(r['target']=='VIOLATION' for r in outcomes),
        final_inconclusive=sum(r['target']=='INCOMPLETE_UNWINDING' for r in latest),no_submission=sum(r['version'] is None for r in latest),
        adjacent_pairs=len(solvers),pairs_reusing_solver=sum(v['mechanism']['actual_disposition']=='keep' for v in solvers.values()),
        peak_estimated_usd=str(sum(Decimal(r['peak_estimate']) for r in outcomes)),offpeak_estimated_usd=str(sum(Decimal(r['off_peak_estimate']) for r in outcomes)))
    secondary=read(evidence/'secondary-properties.json')
    with tarfile.open(evidence/'secondary-raw.tgz') as archive:
        assert archive.extractfile('secondary/summary.json').read()==(evidence/'secondary-properties.json').read_bytes()
        answers={}
        for row in secondary:
            t,v,kind=(row[k] for k in ('task','version','property'));prefix='/'.join(('secondary',t,v,kind))
            assert json.load(archive.extractfile(prefix+'/receipt.json'))==row
            assert row['source_sha256']==props[t][v]['input_sha256']
            assert row['property_sha256']==sha(folder(t).parent/'properties'/(kind+'.prp'))
            result=json.load(archive.extractfile(prefix+'/result.json'))
            rawrows=[r for m in result for r in m.get('result',[])]
            assert {r['property']:r['status'] for r in rawrows}==row['rows']
            for failure in row['failing']:
                r=next(r for r in rawrows if r['property']==failure['property'])
                assert r['status']=='FAILURE' and failure['failure_steps']==sum(s.get('stepType')=='failure' and s.get('property')==r['property'] for s in r['trace'])
            answers[t,v,kind]=row['classification']
    changed=[dict(task=t,version=v,property=k) for (t,v,k),value in answers.items() if v!='P0' and value=='VIOLATION' and answers[t,'P0',k]=='BOUNDED_PASS']
    passed=[r for r in latest if r['outcome']]
    totals.update(secondary_runs=len(secondary),introduced_registered_violations=changed,
        final_primary_pass_without_observed_secondary_regression=sum(not any(i['task']==r['task'] and i['version']==r['version'] for i in changed) for r in passed),
        final_all_registered_safety_confirmed=sum(all(answers[r['task'],r['version'],k]=='BOUNDED_PASS' for k in ('valid-memsafety','no-overflow','no-data-race')) for r in passed))
    save(evidence/'pilot-counts.json',totals);save(evidence/'graph-deltas.json',graphs);save(evidence/'per-task-cycle.json',histories)
    idx=json.loads(gzip.decompress((evidence/'raw/raw-index.json.gz').read_bytes()))
    save(evidence/'release-checks.json',dict(sha256_index=sha(evidence/'raw/raw-index.json.gz'),raw_paths=len(idx['files']),parts=len(idx['archives']),
        compressed_bytes=sum(p['bytes'] for p in idx['archives'].values()),frozen_versions=identities,official_tag_sources=sum(v is not None for v in files.values()),
        missing_at_tag=[k for k,v in files.items() if v is None],audited_native_runs=sum(1 for _ in csv.DictReader((evidence/'trials.csv').open())),
        unique_provider_responses=len(set(ids)),secondary_archive_sha256=sha(evidence/'secondary-raw.tgz'),secondary_runs=len(secondary)))
    print(totals)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('raw',type=Path);p.add_argument('output',type=Path);a=p.parse_args();review(a.raw.resolve(),a.output.resolve())
