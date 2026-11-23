"""Recompute paired timing, resource use, dependency equivalence, models and signed lemma checks."""
import argparse
import csv
import gzip
import json
import statistics
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import file_sha,read
from incdeagle.model.repeat import phase_digest
from scripts.stage7.check_evidence import audit_theory,restore as restore7
from scripts.stage7.oracles import retained_projection
from scripts.stage7.results import runtime_messages
from scripts.stage8.statistics8 import dist,resource,search
from scripts.stage9 import archive
from scripts.stage9.provenance import context as cpp_context
from scripts.stage9.run_matrix import FIRST,OTHER

S7=ROOT/'reports/evidence/stage-07'
S8=ROOT/'reports/evidence/stage-08'
PHASES=('goto','raw_ssa','sc_input','full_model')
ROLES=('before','after')
MODES=('F1','I3')
median=statistics.median


def write_json(path,obj):
    path.write_bytes((json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())


def csvfile(path,rows):
    with path.open('w',newline='',encoding='utf8') as stream:
        keys=list(dict.fromkeys(k for r in rows for k in r))
        writer=csv.DictWriter(stream,fieldnames=keys,lineterminator='\n')
        writer.writeheader()
        for r in rows:writer.writerow({k:round(v,6) if isinstance(v,float) else v for k,v in r.items()})


def need(value,message):
    if not value:raise ValueError(message)


def locate(raw,group,v,c,i,m):
    parent=raw/group/v/c/f'{i:02}'/('off' if group=='formal' else 'on')/m
    receipt=read(parent/'complete.json')
    return parent/receipt['attempt'],receipt


def v1(folder):
    calls=[json.loads(s) for s in (folder/'cpp.jsonl').read_bytes().splitlines()]
    return [{k:c[k] for k in ('unit','argv','files','returncode','output_sha256')} for c in calls]


class Audit:
    def __init__(self,raw,stage7,archive_input):
        self.raw=raw
        self.source=stage7
        self.matrix=read(S7/'matrix.json')
        self.old=read(S7/'summary.json')
        self.s8=read(S8/'native-build.json')
        self.frozen=read(S8/'environment.json')['frozen']
        self.known={}
        self.hashes={}
        self.archive_input=archive_input
        self.counts=dict(candidate_witnesses=0,old_violations=0,models=0,certificates=0,direct_full_models=0,record_pairs=0)
        for c,item in self.matrix.items():
            d=stage7/item['case_dir']
            need(all(file_sha(d/p)==h for p,h in item['files'].items()),'frozen inputs '+c)
            prior=stage7/'trials'/c/'1'
            self.known[c]=(read(d/'phi.json'),read(d/'gamma.json'),
                 read(prior/'old_full/verify/verdict.json'),read(prior/'full/verify/verdict.json'))
    def model(self,p):
        key=file_sha(p)
        if key not in self.hashes:self.hashes[key]=phase_digest(read(p))
        return self.hashes[key]

    def trial(self,group,variant,c,mode,i):
        path,receipt=locate(self.raw,group,variant,c,i,mode)
        cfg=read(path/'settings.json');svc=read(path/'service.json');m=read(path/'measurement.json')
        files=self.matrix[c]['files'];phi,gamma,p0,p1=self.known[c]
        need(cfg['files']==files and cfg['limits']==gamma['limits'] and cfg['case']==c and cfg['mode']==mode
             and cfg['reference_cex0']==self.frozen[c]['old_cex_sha256'] and svc['rc']==0,'frozen run '+str(path))
        need(cfg['affinity']==read(S8/'environment.json')['affinity'] and cfg['repeat']==i,'resource/repeat')
        need(cfg['detail']==(group=='side') and (group!='side' or cfg['observe'] and cfg['stream']),'observation mode')
        new=path/('full' if mode=='F1' else 'pair/candidate')
        old=path/('old_full' if mode=='F1' else 'pair/old')
        if mode=='F1':
            need(m['binary_sha256']==self.s8['development_sha256'],'F1 binary')
            exits=[next(e['rc'] for e in m['processes'] if e['kind']=='wait' and e['role']==role) for role in ('old_full','full')]
        else:
            pair=path/'pair'
            session=read(pair/'session.json')
            need(session['tool']['development_sha256']==self.s8['development_sha256'] and
                 session['command'][1:]==gamma['source_argv']+gamma['verification_output']+['harness.c'],'I3 binary and arguments')
            exits=[session['old_exit'],session['candidate_exit']]
            audit_theory(pair,files)
            self.counts['certificates']+=1
            stats=m['native'];ref=self.old['cases'][c]
            need(stats==session['native'] and stats['reused_prefix_symex_steps']==ref['reused_prefix_steps'] and
                 m['theory']['imported']==ref['lemmas_imported'] and m['fallback_reason']==ref['fallback_reason'],'native reuse '+c)
            reference=self.source/'trials'/c/'1/incremental/pair'
            sc=read(reference/'session.json')['native']['sc_counters']
            need(stats['sc_counters']==sc,'SC counts '+c)
            visits=read(self.source/'diagnostics'/c/'full-model/visits.json')
            if stats['checkpoint_used']:
                kept=stats['reused_prefix_symex_steps']
                first=read(old/'native-stats.json')['executed_dispatches'][:kept]
                second=read(new/'native-stats.json')['executed_dispatches']
                need(first+second==[{k:v[k] for k in ('thread','function','pc')} for v in visits],'dispatch sequence')
            else:need(stats['executed_symex_steps']==len(visits),'full fallback dispatches')
            if variant=='after':
                for folder in (old,pair/'frontend'):
                    evidence=cpp_context(folder)
                    need(not evidence['errors'] and evidence==read(folder/'manifest.json')['context']['frontend_dependencies_v2'],'frontend inclusion proof')
                baseline,_=locate(self.raw,group,'before',c,i,mode)
                for name in ('old','frontend'):
                    need(v1(baseline/'pair'/name)==v1(pair/name),'legacy header/args/output identity '+c)
                    a=read(baseline/'pair'/name/'manifest.json');b=read(pair/name/'manifest.json')
                    shared={k:v for k,v in b['context'].items() if k!='frontend_dependencies_v2'}
                    need(shared==a['context'] and a['preprocessing']==b['preprocessing'] and a['source_sha256']==b['source_sha256'],'v1 manifest '+c)
                    self.counts['record_pairs']+=1
        if group=='side' or mode=='I3':
            phases={k:self.model(new/(k+'.json')) for k in PHASES}
            need(phases==receipt['phase_digests']==self.old['diagnostics'][c]['phases'],'structural model '+c)
            self.counts['models' if mode=='I3' else 'direct_full_models']+=1
        for d,verdict,role,rc in zip((old,new),(p0,p1),('old','candidate'),exits):
            hashes={'program.c':files[role+'/program.c'],'harness.c':files['harness.c']}
            need(all(file_sha(d/n)==h for n,h in hashes.items()),'actual program '+c)
            actual,target=classify((d/'result.json').read_bytes(),rc,phi)
            need(actual==verdict==m['old_verdict' if role=='old' else 'verdict'],'property and unwind '+c)
            need(file_sha(d/'result.json')==receipt[('old_' if role=='old' else '')+'result_sha256'],'raw verdict')
            if actual['classification']=='VIOLATION':
                trace=normalize(target,phi,gamma,hashes,'result.json',version=role)
                need(trace==read(d/('cex0.json' if role=='old' else 'cex1.json')),'witness')
                if role=='old':self.counts['old_violations']+=1
                else:
                    need(c in ('partial_counter','batch_retained') and retained_projection(c,trace),'retained witness')
                    self.counts['candidate_witnesses']+=1
        with gzip.open(path/'samples.json.gz','rt') as stream:points=json.load(stream)
        o,n=[resource(m['times'],k,points) for k in (('old_full','full') if mode=='F1' else ('old_instrumented','incremental'))]
        solver=runtime_messages(new/'result.json')['Solver']*1000
        old_solver=runtime_messages(old/'result.json')['Solver']*1000
        stats=search(new)
        replays=svc['repair_ns']/1e6
        spool=path/'pair/frontend/compiler-spool'
        metrics=path/'pair/frontend/frontend-metrics.json'
        entry=dict(group=group,variant=variant,case=c,mode=mode,rep=i,p0=p0['classification'],p1=p1['classification'],
            launch_ns=svc['launch'],finish_ns=svc['finish'],front_ms=m.get('frontend_seconds',0)*1000 if mode=='I3' else None,
            old_ms=o['wall_ms'],p1_ms=n['wall_ms'],repair_ms=replays,cycle_ms=o['wall_ms']+n['wall_ms']+replays,
            old_cpu_ms=o['cpu_ms'],cpu_ms=n['cpu_ms'],old_rss_kib=o['rss_kib'],rss_kib=n['rss_kib'],
            old_cgroup_kib=o['cg_kib'],cgroup_kib=n['cg_kib'],max_procs=n['procs'],candidate_samples=n['samples'],
            old_solver_ms=old_solver,solver_ms=solver,wrapper_spool_bytes=sum(p.stat().st_size for p in spool.glob('*/*') if p.is_file()) if spool.is_dir() else 0,
            extra_resident_processes=0 if variant=='after' and mode=='I3' and metrics.is_file() else None,
            reduce_ms=read(metrics)['reducer_ns']/1e6 if metrics.is_file() else None,**{
            k:stats.get(k) for k in ('conflicts','decisions','propagations','theory_propagations','restarts','model_variables','model_clauses')})
        if mode=='I3':
            entry.update(fallback=m['fallback_reason'],skipped=m['native']['reused_prefix_symex_steps'],imported=m['theory']['imported'],
                audited=m['theory']['accepted'],binder_ms=m['theory']['audit_ns']/1e6 if m['theory']['audit_ns'] is not None else None,
                old_checkpoint_pss_kib=(m['checkpoint'].get('memory') or {}).get('Pss'))
        return entry

def profile_rows(raw):
    rows=[]
    for c in FIRST:
        for i in range(1,6):
            for v in ROLES:
                d=raw/'frontend'/c/str(i)/v
                p=read(d/'receipt.json')
                g={}
                for line in (d/'gcc.tsv').read_text().splitlines():
                    role,kind,a,b,status=line.split('\t')
                    need(status=='0','GCC trace exit')
                    g.setdefault(role+'_'+kind,[]).append(int(b)-int(a))
                need(all(sum(values)==p[k] for k,values in g.items()) and sorted(map(len,g.values()))==[2,2,3,3],'GCC child boundaries')
                phases=read(S7/'summary.json')['diagnostics'][c]['phases']
                need(p['goto']==phase_digest(read(d/'frontend/goto.json'))==phases['goto'],'profiling model')
                need(p['wall_ns']==p['end_ns']-p['begin_ns'] and p['post_exit_to_end_ns']==p['end_ns']-p['ready_ns'],'profile clocks')
                row=dict(case=c,rep=i,variant=v)
                for k,x in p.items():
                    if k.endswith('_ns') and k not in ('begin_ns','end_ns','ready_ns','launch_ns'):row[k[:-3]+'_ms']=x/1e6
                row.update({k+'_ms':sum(values)/1e6 for k,values in g.items()})
                rows.append(row)
    return rows

def summaries(rows):
    result={}
    normal=[r for r in rows if r['group']=='formal']
    for c in FIRST:
        selected={(r['variant'],r['mode'],r['rep']):r for r in normal if r['case']==c}
        pairs=[(selected['before','F1',i],selected['before','I3',i],selected['after','F1',i],selected['after','I3',i]) for i in range(1,6)]
        metrics={}
        for v in ROLES:
            for m in MODES:
                g=[selected[v,m,i] for i in range(1,6)]
                metrics[v+'_'+m]={k:dist(r.get(k) for r in g) for k in ('front_ms','p1_ms','old_ms','cycle_ms','cpu_ms','old_cpu_ms','rss_kib','old_rss_kib','cgroup_kib','old_cgroup_kib','max_procs','solver_ms','wrapper_spool_bytes','old_checkpoint_pss_kib','binder_ms')}
        comparisons={}
        for k,values in dict(front_saved=[b['front_ms']-d['front_ms'] for a,b,e,d in pairs],
                before_i3_minus_f1=[b['p1_ms']-a['p1_ms'] for a,b,e,d in pairs],
                after_i3_minus_f1=[d['p1_ms']-e['p1_ms'] for a,b,e,d in pairs],
                i3_saved=[b['p1_ms']-d['p1_ms'] for a,b,e,d in pairs],
                i3_old_saved=[b['old_ms']-d['old_ms'] for a,b,e,d in pairs],
                i3_cycle_saved=[b['cycle_ms']-d['cycle_ms'] for a,b,e,d in pairs],
                i3_solver_saved=[b['solver_ms']-d['solver_ms'] for a,b,e,d in pairs],
                f1_delta=[e['p1_ms']-a['p1_ms'] for a,b,e,d in pairs],
                remaining_non_solver=[d['p1_ms']-e['p1_ms']-(d['solver_ms']-e['solver_ms']) for a,b,e,d in pairs]).items():
            comparisons[k]={'values':values,**dist(values)}
        result[c]=dict(groups=metrics,paired=comparisons,
             front_goal=metrics['after_I3']['front_ms']['median']<=110 and comparisons['front_saved']['median']>=100,
             faster_repeats=sum(x<0 for x in comparisons['after_i3_minus_f1']['values']))
    return result


def development_summary(root):
    result={}
    for c in FIRST:
        values={}
        for variant in ROLES:
            front=[];paired=[]
            for i in range(1,6):
                observed={}
                for mode,tag in [('I3','incremental'),('F1','full')]:
                    f,_=locate(root,'formal',variant,c,i,mode)
                    m=read(f/'measurement.json');clocks=m['times']
                    observed[mode]=(clocks[tag+'_end']['monotonic_ns']-clocks[tag+'_start']['monotonic_ns'])/1e6
                    if mode=='I3':front.append(1000*m['frontend_seconds'])
                paired.append(observed['I3']-observed['F1'])
            values[variant]={'front_ms':dist(front),'i3_minus_f1_ms':dist(paired),'paired_values':paired}
        result[c]=values
    return result


def derive(raw,stage7,dest,development=None):
    dest.mkdir(parents=True,exist_ok=True)
    audit=Audit(raw,stage7,False)
    rows=[]
    for group in ('formal','side'):
        plan=read(raw/group/'schedule.json')['schedule']
        cases=FIRST if group=='formal' else (*FIRST,*OTHER)
        repeats=5 if group=='formal' else 1
        expected={(v,c,m,i,group=='side') for v in ROLES for c in cases for m in MODES for i in range(1,repeats+1)}
        need(len(plan)==len(expected) and set(map(tuple,plan))==expected,'balanced schedule')
        last=0
        for v,c,m,i,detail in plan:
            r=audit.trial(group,v,c,m,i)
            need(r['launch_ns']>=last and r['launch_ns']<r['finish_ns'],'nonserial trials')
            last=r['finish_ns'];rows.append(r)
    streams={}
    for c in (*FIRST,*OTHER):
        case={}
        for mode in MODES:
            folders=[locate(raw,'side',v,c,1,mode)[0]/('full' if mode=='F1' else 'pair/candidate') for v in ROLES]
            entry={}
            for f in ('s8-input.bin','s8-graph.tsv','s8-sat.tsv','s8-trace.tsv','s8-search.tsv'):
                a,b=[d/f for d in folders]
                need(a.exists()==b.exists(),'unequal artifact availability')
                if a.is_file():
                    ha,hb=file_sha(a),file_sha(b)
                    entry[f]=dict(bytes=a.stat().st_size,before=ha,after=hb,equal=ha==hb)
            need('s8-input.bin' in entry,'no captured input '+c)
            if c=='fib_updates_8':
                need(len(entry)==5 and all(r['equal'] for r in entry.values()),
                     'Fibonacci solver input, theory graph or search changed in '+mode)
            case[mode]=entry
        streams[c]=case
    controls=profile_rows(raw)
    negatives={}
    for n in ('header','macro_flag','compiler_config','abi','alias','nested','unknown_dependency','missing_attachment','damaged_stream','syntax','gcc_error','resources'):
        d=raw/'audit/negative'/n
        doc=read(d/'receipt.json')
        if n not in ('syntax','gcc_error','resources'):
            s=read(d/'pair/session.json')
            need(s['candidate']['classification']==doc['p1'] and s['path']==doc['path'],'negative native '+n)
            target=read(d/'input/batch_total/phi.json')
            independent,_=classify((d/'independent/result.json').read_bytes(),doc['independent_exit'],target)
            need(independent==s['candidate'],'negative independent '+n)
            if n!='alias':need(doc['skipped']==0 and doc['imported']==0 and read(d/'pair/candidate/native-import.json')['rows']==[],'negative cache use '+n)
            old,front=[read(d/'pair'/side/'manifest.json')['context']['frontend_dependencies_v2'] for side in ('old','frontend')]
            if n in ('header','abi'):
                need(any(k.endswith('/headers/entry.h') and front['headers'].get(k)!=v for k,v in old['headers'].items()),'changed header '+n)
            if n=='alias':need(old['headers']==front['headers'] and old['units']==front['units'],'header alias')
            if n=='nested':
                need(any(k.endswith('/headers/left.h') for k in old['headers'].keys()-front['headers'].keys()) and
                     any(k.endswith('/headers/right.h') for k in front['headers'].keys()-old['headers'].keys()),'conditional dependency')
            if n=='compiler_config':need(old['compiler']['cc1']!=front['compiler']['cc1'] and front['errors'],'compiler reconfiguration')
            if n=='macro_flag':need(old['units']!=front['units'],'macro arguments')
        elif n in ('syntax','gcc_error'):
            state=read(d/'run/workflow.json')
            need(doc['cli_rc']==2 and state['status']==doc['status']=='INVALID_PATCH' and not state['baseline_started'],'invalid candidate '+n)
            if n=='gcc_error':
                calls=next((d/'run').rglob('frontend/frontend-calls.jsonl'))
                need(any(json.loads(line).get('returncode',0)!=0 for line in calls.read_bytes().splitlines()),'GCC failure')
        else:
            need(read(d/'oom/service.json')['resource_status']=='OOM' and b'Wrong cgroup limit' in (d/'wrong-budget.stderr').read_bytes()
                 and doc['timeout'] and not doc['child_live'] and doc['leader_exit']!=0,'resource controls')
        negatives[n]=doc
    eq=read(raw/'audit/equivalence/checks.json')
    for r in eq:
        d=raw/'audit/equivalence'/r['case']
        need(all((d/'reference'/n).read_bytes()==(d/'optimized'/n).read_bytes() for n in ('stdout','stderr','exit')),'GCC bytes')
        if (d/'reference/cpp.jsonl').exists():
            need(json.loads((d/'reference/cpp.jsonl').read_bytes())==json.loads((d/'optimized/cpp.jsonl').read_bytes()),'GCC v1')
            r['fields']={k:True for k in json.loads((d/'reference/cpp.jsonl').read_bytes())}
    cli={}
    for c,n in [('batch_total',1),('fib_updates_8',14)]:
        d=raw/'audit/production'/c
        doc=read(d/'receipt.json');workflow=read(d/'run/workflow.json')
        need(doc['imported']==n and doc['model_match'] and workflow['status']=='COMPLETED' and workflow['repair_usage']['api_calls']==0,'production CLI '+c)
        audit_theory(d/'run/pair',audit.matrix[c]['files'])
        cli[c]=doc
    results=summaries(rows)
    csvfile(dest/'trials.csv',rows);csvfile(dest/'frontend-profile.csv',controls)
    write_json(dest/'paired.json',results);write_json(dest/'solver-inputs.json',streams)
    write_json(dest/'negative-results.json',negatives);write_json(dest/'gcc-equivalence.json',eq)
    write_json(dest/'production-cli.json',cli)
    write_json(dest/'verification.json',dict(formal=sum(r['group']=='formal' for r in rows),regression=sum(r['group']=='side' for r in rows),
               frontend_profiles=len(controls),cases=list((*FIRST,*OTHER)),negative_checks=len(negatives),gcc_controls=len(eq),**audit.counts))
    if development is not None:write_json(dest/'development.json',development_summary(development))
    from scripts.stage9 import tables
    tables.render(raw,dest)
    print('Recomputed',len(rows),'verifications,',len(controls),'frontend profiles,',audit.counts,flush=True)
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path);p.add_argument('--stage7',type=Path)
    p.add_argument('--write',type=Path);p.add_argument('--development',type=Path);p.add_argument('--evidence',type=Path,default=ROOT/'reports/evidence/stage-09')
    a=p.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        t=Path(temp)
        raw=a.raw or t/'raw';stage7=a.stage7 or t/'stage7';dest=a.write or t/'derived'
        if a.raw is None:archive.unpack(a.evidence,raw)
        if a.stage7 is None:
            stage7.mkdir();restore7(S7,stage7)
        development=a.development or (raw/'development' if (raw/'development').is_dir() else None)
        derive(raw,stage7,dest,development)
        if not a.write:
            for f in dest.iterdir():need(file_sha(f)==file_sha(a.evidence/f.name),'published output '+f.name)
            print('All',len(list(dest.iterdir())),'published numerical outputs match byte-for-byte.',flush=True)
