"""Recompute timings, paired contrasts, CPU savings, uncertainty and cost ledgers from raw trials."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import statistics as st
import sys
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import read
from scripts.stage7.results import runtime_messages,source_cost

MODES=('F0','F1','F2','I1','I2','I3')
COMPARISONS=(('F0','F1'),('F1','F2'),('F2','I1'),('I1','I2'),('I2','I3'),('F1','I3'))
COSTS=('front','dispatch','sc','encode','solver','restore','change','theory','observer','residual')
def ms(n):return n/1e6 if n is not None else None
def rnd(n):return round(n,6) if n is not None else None
def avg(xs):return st.fmean(xs)
def dist(seq):
    xs=sorted(x for x in seq if x is not None)
    if not xs:return None
    q=st.quantiles(xs,n=4,method='inclusive') if len(xs)>1 else xs*3
    lo=q[0]-1.5*(q[2]-q[0]);hi=q[2]+1.5*(q[2]-q[0])
    return {**{k:rnd(v) for k,v in [('median',st.median(xs)),('min',xs[0]),('max',xs[-1]),('q1',q[0]),('q3',q[2]),('mean',avg(xs))]},
            'n':len(xs),'outliers':[rnd(x) for x in xs if x<lo or x>hi]}

def native(folder):
    p=folder/'s8-native.tsv'
    if not p.is_file():return {}
    result={}
    for line in p.read_text().splitlines():
        key,*values=line.split('\t')
        result[key]=list(map(int,values))
    return result

@lru_cache(maxsize=1)
def complete_models():
    return read(ROOT/'reports/evidence/stage-07/summary.json')['diagnostics']

def io(mark,key):
    return sum(int(p.split('=')[1]) for row in mark['io_stat'].splitlines() for p in row.split()[1:] if p.startswith(key+'='))
def resource(times,role,points):
    a,b=times[role+'_start'],times[role+'_end']
    taken=[p for p in points if a['monotonic_ns']<=p[0]<=b['monotonic_ns']]
    return {'wall_ms':ms(b['monotonic_ns']-a['monotonic_ns']),'cpu_ms':(b['cpu_usage_us']-a['cpu_usage_us'])/1000,
            'rss_kib':max((p[1] for p in taken),default=None),'cg_kib':max((p[2] for p in taken),default=None),
            'procs':max((p[3] for p in taken),default=None),'samples':len(taken),
            'read_bytes':io(b,'rbytes')-io(a,'rbytes'),'write_bytes':io(b,'wbytes')-io(a,'wbytes')}

def search(folder):
    stdout=(folder/'diagnostic.stdout').read_bytes()
    mat=re.search(rb'ClosureSolver finishes with (\d+) conflicts, (\d+) decisions, and (\d+) propagations\. (\d+) theory propagations and (\d+) cycles',stdout)
    counts=dict(zip(('conflicts','decisions','propagations','theory_propagations','theory_cycles'),map(int,mat.groups()))) if mat else {}
    file=folder/'s8-search.tsv'
    if file.exists():
        starts,*values=map(int,file.read_text().split())
        if list(counts.values())!=values:raise ValueError('Search counters disagree '+str(folder))
        counts['starts']=starts
        counts['restarts']=max(0,starts-1)
    elif (folder/'s8-sat.tsv').exists() and native(folder).get('search',[1])[0]==0:
        # Root propagation during construction can precede solve_ and is not
        # printed on its early-return path. Only the search call count is known.
        counts={'starts':0,'restarts':0}
    nums=None
    for r in read(folder/'result.json'):
        m=re.fullmatch(r'(\d+) variables, (\d+) clauses',r.get('messageText',''))
        if m:nums=list(map(int,m.groups()))
    counts['model_variables'],counts['model_clauses']=nums or [None,None]
    p=folder/'s8-sat.tsv'
    if p.exists():
        v,c,vhash,chash=p.read_text().split()
        counts.update(var_submissions=int(v),clause_submissions=int(c),var_order=vhash,clause_order=chash)
    p=folder/'s8-graph.tsv'
    if p.exists():
        graph=p.read_bytes()
        counts['graph_sha256']=hashlib.sha256(graph).hexdigest()
        counts['graph_edges']=sum(x.startswith(b'edge\t') for x in graph.splitlines())
        counts['graph_guards']=sum(x.startswith(b'guard\t') for x in graph.splitlines())
        edges=[x.split(b'\t')[3] for x in graph.splitlines() if x.startswith(b'edge\t')]
        counts['graph_rf_edges']=edges.count(b'rf')
        counts['graph_po_apo_edges']=edges.count(b'po')+edges.count(b'apo')
    p=folder/'s8-trace.tsv'
    if p.exists():counts['early_trace_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    return counts

def read_trial(formal,plan):
    case,mode,rep,detail=plan
    label='on' if detail else 'off'
    parent=formal/case/f'{rep:02}'/label/mode
    proof=read(parent/'complete.json')
    folder=parent/proof['attempt']
    settings=read(folder/'settings.json')
    m=read(folder/'measurement.json')
    svc=read(folder/'service.json')
    assert svc['rc']==0 and settings['mode']==mode and settings['detail']==detail and settings['case']==case
    raw=bool(mode in ('F0','F1'))
    candidate=folder/('full' if raw else 'pair/candidate')
    old=folder/('old_full' if raw else 'pair/old')
    front=folder/'pair/frontend'
    ni,no,nf=map(native,(candidate,old,front))
    with gzip.open(folder/'samples.json.gz','rt') as f:points=json.load(f)
    c,o=[resource(m['times'],role,points) for role in (('full','old_full') if raw else ('incremental','old_instrumented'))]
    theory=m.get('theory',{})
    mc=m.get('native',{})
    sc=mc.get('sc_counters',{})
    cr,orr=map(lambda f:runtime_messages(f/'result.json'),(candidate,old))
    replay=ms(svc['repair_ns'])
    hist=source_cost(case)['seconds']
    r={'case':case,'rep':rep,'mode':mode,'detail':detail,'classification':proof['verdict'],'path':m['path'],
       'reason':m.get('fallback_reason'),'old_classification':m['old_verdict']['classification'],
       'candidate_sha256':proof['candidate_sha256'],'old_sha256':proof['old_sha256'],'protected_unit':settings['reference_cex0'],
       'model_phases':len(proof['phase_digests']),'replay_ms':replay,'cycle_ms':c['wall_ms']+o['wall_ms']+replay,
       'cycle_historical_ms':c['wall_ms']+o['wall_ms']+hist*1000 if hist is not None else None,
       'solver_ms':1000*cr['Solver'],'old_solver_ms':1000*orr['Solver'],'frontend_ms':1000*m.get('frontend_seconds',0),
       'change_ms':1000*m.get('change_analysis_seconds',0),'skipped':mc.get('reused_prefix_symex_steps',0),
       'new_dispatch':mc.get('executed_symex_steps'),'ctrl_maxrss_kib':m['controller_maxrss_kib'],
       'checkpoint_pss_kib':(m['checkpoint'].get('memory') or {}).get('Pss'),
       'checkpoint_private_kib':sum((m['checkpoint'].get('memory') or {}).get(k,0) for k in ('Private_Dirty','Private_Clean')) if m['checkpoint'] else None,
       'generated_rf':sc.get('read_bundles_generated'),'reused_rf':sc.get('rf_edges_reused',0),
       'reused_po':sc.get('thread_edges_reused',0),'reused_value':sc.get('value_formulas_reused',0),'reused_cover':sc.get('coverage_formulas_reused',0),
       'accepted':theory.get('accepted',0),'imported':theory.get('imported',0),'exported':theory.get('exported',0),
       'withheld':theory.get('not_submitted',0),'audit_ms':ms(theory.get('audit_ns')),'bind_ms':ms(theory.get('binding_ns')),
       'import_ms':ms(theory.get('import_ns')),'old_audit_ms':ms(theory.get('old_audit_ns')),'snapshot_ms':ms(theory.get('new_fingerprint_ns')),
       'old_snapshot_ms':ms(theory.get('old_fingerprint_ns')),
       **dict(c),**{'old_'+k:v for k,v in o.items()},**search(candidate),**{'old_'+k:v for k,v in search(old).items()}}
    diag=complete_models()[case]
    r.update(full_dispatch=diag['full_dispatches'],full_events=diag['events'],full_rf_formulas=diag['rf_constraints'],
             kept_events=mc.get('checkpoint_raw_events',0) if mc.get('checkpoint_used') else 0)
    r.update(rebuilt_events=r['full_events']-r['kept_events'],
             rebuilt_rf_formulas=r['full_rf_formulas']-r['reused_value']-r['reused_cover'])
    if 'graph_rf_edges' in r:
        r.update(rebuilt_rf_edges=r['graph_rf_edges']-r['reused_rf'],rebuilt_po_apo=r['graph_po_apo_edges']-r['reused_po'])
    if not raw:
        session=read(folder/'pair/session.json')
        r['fork_ms']=ms(session['old_native']['checkpoint_fork_ns'])
        for k,f in [('fragment_bytes',old/'fragments.irep'),('goto_image_bytes',front/'goto.irep'),('lemma_cache_bytes',old/'lemma-cache.json')]:
            r[k]=f.stat().st_size if f.exists() else None
    extra={}
    if detail:
        assert ni and no and (raw or nf)
        for role,n in [('candidate',ni),('old',no),('frontend',nf)]:
            for k,v in n.items():
                if k!='span':extra[role+'.'+k]={'calls':v[0],'wall_ms':ms(v[1]),'cpu_ms':ms(v[2])}
        def ncost(k):return ms(ni[k][1])
        ledger={'front':r['frontend_ms']+ncost('front'),'dispatch':ncost('prefix_dispatch')+ncost('other_dispatch'),
                'sc':ncost('sc'),'encode':ncost('encode_graph')-ncost('lemma_prepare'),
                'solver':r['solver_ms']-ncost('lemma_submit'),'restore':ncost('irep_read')+ncost('rebind')+ncost('prefix_symbols'),
                'change':r['change_ms'],'theory':ncost('lemma_prepare')+ncost('lemma_submit'),
                'observer':ncost('observer_equation')+ncost('goto_json')}
        # Use the measurement host's left-to-right addition on every Python version.
        # Built-in float sum changed in Python 3.12 and can change the last output bits.
        accounted_ms=0.0
        for duration_ms in ledger.values():
            accounted_ms+=duration_ms
        ledger['residual']=r['wall_ms']-accounted_ms
        if ledger['residual']<-.1:raise ValueError('Overlapping candidate cost spans '+str(folder))
        r.update({'ledger_'+k+'_ms':v for k,v in ledger.items()})
        r.update(prefix_cpu_ms=ms(ni['prefix_dispatch'][2]),prefix_wall_ms=ncost('prefix_dispatch'),
                 region_gen_cpu_ms=ms(ni['rf_selected'][2]+ni['po_selected'][2]),region_gen_wall_ms=ncost('rf_selected')+ncost('po_selected'),
                 sc_cpu_ms=ms(ni['sc'][2]),dispatch_cpu_ms=ms(ni['prefix_dispatch'][2]+ni['other_dispatch'][2]),
                 encode_ms=ncost('encode_graph')-ncost('lemma_prepare'),graph_load_ms=ncost('graph_load'),
                 ssa_cnf_ms=ncost('ssa_convert'),search_cpu_ms=ms(ni['search'][2]),worker_ms=ncost('lemma_worker'),
                 old_irep_write_ms=ms(no['irep_write'][1]),restore_read_ms=ncost('irep_read'),
                 rebind_ms=ncost('rebind'),symbol_check_ms=ncost('prefix_symbols'))
        if nf:
            gcc=[json.loads(s) for s in (front/'s8-gcc.jsonl').read_bytes().splitlines()]
            r.update(front_preprocess_ms=ms(nf['preprocess'][1]),front_gcc_ms=ms(sum(t['gcc_wall_ns'] for t in gcc)),
                     front_parse_ms=ms(nf['parse'][1]),front_goto_ms=ms(nf['goto_convert'][1]),front_goto_json_ms=ms(nf['goto_json'][1]),
                     front_irep_ms=ms(nf['irep_write'][1]),front_typecheck_ms=ms(nf['typecheck'][1]),front_gcc_calls=len(gcc),
                     front_native_ms=ms(nf['span'][1]-nf['span'][0]))
        for role,sub in [('controller',m['python_spans']),('binder',read(candidate/'s8-binder.json') if (candidate/'s8-binder.json').exists() else {})]:
            for k,v in sub.items():
                extra[role+'.'+k]={'calls':v[0],'wall_ms':ms(v[1]),'cpu_ms':ms(v[2]),'exclusive_wall_ms':ms(v[3]),'exclusive_cpu_ms':ms(v[4])}
    return r,extra

def csvfile(dest,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with dest.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys,lineterminator='\n');w.writeheader()
        for row in rows:w.writerow({k:rnd(v) if isinstance(v,float) else v for k,v in row.items()})

def summarize(rows):
    allcases=list(dict.fromkeys(r['case'] for r in rows))
    grouped=defaultdict(dict)
    for r in rows:
        key=(r['case'],r['mode'],r['detail'])
        if r['rep'] in grouped[key]:raise ValueError('Duplicate trial')
        grouped[key][r['rep']]=r
    sums=[];pairs=[];budget=[];caps=[]
    for (case,mode,detail),table in grouped.items():
        first=next(iter(table.values()))
        stats={k:dist([r.get(k) for r in table.values()]) for k,v in first.items() if isinstance(v,(int,float)) and k not in ('rep','detail')}
        sums.append(dict(case=case,mode=mode,detail=detail,**stats))
    def matched(key1,key2):
        a,b=grouped[key1],grouped[key2]
        return [(a[n],b[n]) for n in sorted(a.keys()&b.keys())]
    for case in allcases:
        for a,b in COMPARISONS:
            for detail in (False,True):
                q=matched((case,a,detail),(case,b,detail))
                if not q:continue
                metrics=['wall_ms','cpu_ms','old_wall_ms','old_cpu_ms','cycle_ms','solver_ms','old_solver_ms','rss_kib','old_rss_kib','conflicts','decisions','propagations','theory_propagations','restarts','sc_cpu_ms','dispatch_cpu_ms','search_cpu_ms','encode_ms']
                diff={k:dist(y[k]-x[k] for x,y in q if x.get(k) is not None and y.get(k) is not None) for k in metrics}
                pairs.append(dict(case=case,left=a,right=b,detail=detail,**diff))
        q=matched((case,'F1',True),(case,'I3',True))
        if q:
            dd={k:avg(y['ledger_'+k+'_ms']-x['ledger_'+k+'_ms'] for x,y in q) for k in COSTS}
            total=avg(y['wall_ms']-x['wall_ms'] for x,y in q)
            assert abs(total-sum(dd.values()))<1e-5
            budget.append({'case':case,'n':len(q),'delta_ms':total,**{k+'_ms':v for k,v in dd.items()}})
            mech=[x['prefix_wall_ms']+x['region_gen_wall_ms'] for x,y in q]
            cap1=[x['wall_ms']/(x['wall_ms']-s) for (x,y),s in zip(q,mech)]
            cap2=[x['wall_ms']/(x['encode_ms']+x['solver_ms']) for x,y in q]
            normal=matched((case,'F1',False),(case,'I3',False))
            saving=st.median(x['wall_ms']-y['wall_ms'] for x,y in normal) if normal else None
            startup=st.median(y['old_wall_ms']-x['old_wall_ms'] for x,y in normal) if normal else None
            caps.append({'case':case,'measured_targeted_wall_ms':st.median(mech),
                'measured_targeted_cpu_ms':st.median(x['prefix_cpu_ms']+x['region_gen_cpu_ms'] for x,y in q),
                'targeted_share_pct':st.median(100*s/x['wall_ms'] for (x,y),s in zip(q,mech)),
                'upper_existing_prefix_and_regions':st.median(cap1),'upper_if_only_encode_and_solve_remain':st.median(cap2),
                'candidate_saving_normal_ms':saving,'extra_warmup_normal_ms':startup,
                'break_even_uses':max(1,math.ceil(max(0,startup)/saving)) if saving is not None and saving>0 else None})
    return {'groups':sums,'contrasts':pairs,'ledgers':budget,'bounds':caps}

def derive(formal,dest,partial=False):
    plan=read(formal/'plan.json')
    rows=[];timings=[]
    for q in plan['schedule']:
        c,m,i,d=q
        if partial and not (formal/c/f'{i:02}'/('on' if d else 'off')/m/'complete.json').exists():continue
        row,extra=read_trial(formal,q)
        rows.append(row)
        timings += [dict(case=c,mode=m,rep=i,detail=d,operation=k,**v) for k,v in extra.items()]
    dest.mkdir(parents=True,exist_ok=True)
    csvfile(dest/'ablation-results.csv',rows)
    csvfile(dest/'phase-times.csv',timings)
    results=summarize(rows)
    csvfile(dest/'case-ledgers.csv',results['ledgers'])
    csvfile(dest/'bounds.csv',results['bounds'])
    (dest/'summary.json').write_bytes((json.dumps(results,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode())
    print('Recomputed',len(rows),'verification paths,',len(timings),'phase observations,',len(results['ledgers']),'ledgers',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('formal',type=Path);p.add_argument('dest',type=Path)
    p.add_argument('--partial',action='store_true');a=p.parse_args();derive(a.formal,a.dest,a.partial)
