"""Compute paired wall differences from fixed source and native timer boundaries."""
import collections,json,statistics,sys
from pathlib import Path
from audit import read,save
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'stage11b'))
from raw_store import archive
def group(root):
    rows=read(root/'trials.json');idx=read(root/'raw/files.json');cases={};sc=read(root/'witnesses.json')
    def stats(values):
        return dict(values=values,median=statistics.median(values),range=[min(values),max(values)],faster=sum(x>0 for x in values))
    with archive(root/'raw') as z:
        for case in sorted({p['case'] for p in rows}):
            case_rows=[p for p in rows if p['case']==case]
            stock=next(p for p in case_rows if p['mode']=='stock')
            pairs={}; counts={}
            for p in case_rows:
                def raw(side,n):
                    k=f"formal/{case}/{p['trial']}/{p['mode']}/{side}/{n}"
                    if k not in idx:return None
                    h=idx[k];return z.read(h)
                if p['mode']=='stock':continue
                for i,r in enumerate(p['sides']):
                    control=stock['sides'][i]
                    assert all(r[k]==control[k] for k in ('stream','source','graph','argv','phases','exit'))
                    assert [(x,y) for x,y,_ in r['properties']]==[(x,y) for x,y,_ in control['properties']]
                    assert r['gate']['native']['path']=='ACCEPT_NATIVE_RESTRICTED'
                    assert not r['model_reuse'] and (r['exit']!=10 or sc[r['witness']]['status']=='EXPLICIT_SC_ORDER')
                new=p['sides'][1];old=p['sides'][0];n=new['counters'];o=old['counters']
                val={k:n[k] for k in ('decisions','conflicts','propagations','starts','theory_conflicts','theory_propagations','postsolve_learnts','actually_reattached','rup_proved','peak_rss_kib','resident_Pss_kib')}
                val.update(static_used=new['closure']['used_derived'],p0_solver_rss=o['peak_rss_kib'],controller_hwm_kib=new['memory']['after']['VmHWM'],
                           p0_decisions=o['decisions'],p0_theory_conflicts=o['theory_conflicts'])
                for k,v in [('search',new['timings']['search_ns']),('search_cpu',new['timings']['search_cpu_ns']),
                     ('p1_solver_total',new['markers']['decider_return']-new['markers']['model_ready']),
                     ('p1_program',new['timings']['program_ns']),('cycle',p['controller_with_gate_ns']),('p0_program',old['timings']['program_ns']),
                     ('p0_search',old['timings']['search_ns']),('p0_native_snapshot',o['dynamic_snapshot_ns']),
                     ('p0_instrumented_analysis',o['instrumented_analyze_ns']),('p0_native_flush',o['proof_flush_ns']),
                     ('switch',n['init_switch_ns']),('submit',n['submit_ns']),('native_install',n['install_ns']),
                     ('p1_full_front',new['timings']['pre_bridge_ns']),('p1_binding_and_audit',new['timings']['bind_delta_ns'])]:
                    val[k+'_ms']=v/1e6
                for where,row,tag in [('capture-time',old,'p0'),('review-time',new,'p1')]:
                    for k,v in row.get(where,{}).items():
                        if k.endswith('_ns'):val[tag+'_'+k[:-3]+'_ms']=v/1e6
                val['p0_preparation_ms']=val['p0_program_ms']+val.get('p0_total_ms',0)
                val['child_cpu_s']=p['children_user_s']+p['children_system_s'];val['controller_cpu_s']=p['controller_cpu_ns']/1e9
                report={'imports':{},'hits':{}}
                u=raw('new','worker/use.tsv')
                for line in u.decode().splitlines() if u else []:
                    rec=line.split('\t')
                    if rec[0]=='hit':report['hits'].setdefault(rec[1],{})[rec[2]]=int(rec[3])
                    if rec[0]=='import':report['imports'][rec[1]]=rec[2]
                if raw('new','audit.json.gz'):
                    import gzip
                    d=json.loads(gzip.decompress(raw('new','audit.json.gz')));library=json.loads(gzip.decompress(raw('old','library.json.gz')))
                    report.update(p0=library['counts'],p0_theory=collections.Counter(library['theory_decisions'].values()),
                                  p0_mixed=collections.Counter(library['mixed_decisions'].values()),p1_theory=collections.Counter(d['theory_decisions'].values()),
                                  p1_mixed=collections.Counter(d['mixed_decisions'].values()),
                                  p1_conflict_proved=sum(v=='P1_PROVED' and library['theories'][i]['origin']!='reverse_rf' for i,v in d['theory_decisions'].items()),
                                  p1_mapped_theory=sum(v!='unbound_semantic_literal' for v in d['theory_decisions'].values()),
                                  root_checked=len(d['native_root_checks']))
                pairs[p['trial'],p['mode']]=val;counts[p['trial'],p['mode']]=report
            results={}
            for mode in ('F','B','T','C','TC'):
                series=[(t,v) for (t,m),v in sorted(pairs.items()) if m==mode]
                med={k:statistics.median([v.get(k,0) for t,v in series]) for k in sorted(set().union(*(v for _,v in series)))}
                paired={}
                for ref in ('F','B','T'):
                    paired[ref]={k:stats([pairs[t,ref][k]-v[k] for t,v in series]) for k in
                      ('search_ms','p1_solver_total_ms','p1_program_ms','cycle_ms','p0_preparation_ms','decisions','conflicts','propagations','theory_propagations','theory_conflicts')}
                results[mode]=dict(repeats=len(series),median=med,paired=paired,individual=[dict(trial=t,**v,reuse=counts[t,mode]) for t,v in series])
            cases[case]=dict(stock=[dict(program_ms=r['timings']['program_ns']/1e6,search_ms=r['timings']['search_ns']/1e6,
                      solver_total_ms=(r['markers']['decider_return']-r['markers']['model_ready'])/1e6,exit=r['exit']) for r in stock['sides']],modes=results)
    save(root,'summary.json',cases)
    for c,rec in cases.items():
        for m,t in rec['modes'].items():
            p=t['paired']['F'];print(c,m,*(round(p[k]['median'],2) for k in ('search_ms','p1_solver_total_ms','cycle_ms')),t['individual'][0]['reuse']['imports'])
if __name__=='__main__':group(Path(sys.argv[1]))
