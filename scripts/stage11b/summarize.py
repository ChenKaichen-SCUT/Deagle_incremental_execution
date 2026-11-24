"""Check raw receipts, native search identity, actual admissions and paired measurements."""
from pathlib import Path
import collections,hashlib,json,statistics,sys,zipfile
from raw_store import archive
def median(a):return statistics.median(a)
def run(root):
    raw=root/'raw';files=json.loads((raw/'files.json').read_bytes())
    rows=json.loads((root/'trials.json').read_bytes());summary={}
    witnesses=json.loads((root/'witnesses.json').read_bytes())
    with archive(raw) as z:
        assert set(z.namelist())==set(files.values())
        for h in z.namelist():
            if hashlib.sha256(z.read(h)).hexdigest()!=h:raise ValueError(h)
        for case in sorted({p['case'] for p in rows}):
            series=[p for p in rows if p['case']==case]
            reference=next(p for p in series if p['mode']=='stock');pairs={(p['trial'],p['mode']):p for p in series}
            results={}
            for mode in ('F','G','S','GS'):
                data=sorted((p for p in series if p['mode']==mode),key=lambda p:p['trial'])
                if not data:continue
                stats=collections.defaultdict(list);diff=collections.defaultdict(list)
                for p in data:
                    for i,r in enumerate(p['sides']):
                        stock=reference['sides'][i]
                        assert all(r[k]==stock[k] for k in ('source','argv','stream','graph','phases','exit'))
                        assert [(a,b) for a,b,_ in r['properties']]==[(a,b) for a,b,_ in stock['properties']]
                    r=p['sides'][1];base=pairs[p['trial'],'F'];cold=base['sides'][1]
                    if r['root_check'] or cold['root_check']:assert r['root_check']==cold['root_check']
                    for key,series_key in [('search_ns','search_ms'),('program_ns','p1_wall_ms'),('bind_delta_ns','bind_ms'),('pre_bridge_ns','before_bridge_ms'),('cnf_graph_ns','cnf_graph_ms')]:
                        stats[series_key].append(r['timings'][key]/1e6)
                    for key in ('root_prepare_ns','derive_ns','retract_ns'):stats[key[:-3]+'_ms'].append(r['closure'][key]/1e6)
                    for key in ('init_switch_ns','submit_ns','rup_ns','parse_ns'):stats[key[:-3]+'_ms'].append(r['counters'][key]/1e6)
                    for key in ('decisions','conflicts','starts','propagations','theory_conflicts','theory_propagations','actually_reattached','rup_proved','rup_unmapped','rup_unproved','rup_unchecked','peak_rss_kib','resident_Pss_kib','arena_bytes'):
                        stats[key].append(r['counters'][key])
                    for key in ('K_derived','O','recovered','added','deleted','affected_instances','used_derived','cached_joins','cached_rows','cartesian_pairs_bypassed','rule_checks','fired_instances','rf_activations','guard_activations','dynamic_co_pairs','push','pop'):
                        stats[key].append(r['closure'][key])
                    stats['p0_wall_ms'].append(p['sides'][0]['timings']['program_ns']/1e6)
                    stats['pair_application_ms'].append(p['application_pair_ns']/1e6)
                    stats['pair_controller_ms'].append(p['controller_cycle_ns']/1e6)
                    for field in ('postcheck_ns','controller_with_gate_ns','controller_cpu_ns'):
                        if field in p:stats[field[:-3]+'_ms'].append(p[field]/1e6)
                    for field in ('children_user_s','children_system_s'):
                        if field in p:stats[field].append(p[field])
                    stats['search_trace_equals_stock'].append(int(r['search_trace']==reference['sides'][1]['search_trace']))
                    diff['F_minus_mode_P1_ms'].append((cold['timings']['program_ns']-r['timings']['program_ns'])/1e6)
                    diff['F_minus_mode_pair_ms'].append((base['application_pair_ns']-p['application_pair_ns'])/1e6)
                    diff['F_minus_mode_search_ms'].append((cold['timings']['search_ns']-r['timings']['search_ns'])/1e6)
                results[mode]=dict(repetitions=len(data),median={k:median(v) for k,v in stats.items()},
                    paired={k:dict(values=v,median=median(v),positive=sum(x>0 for x in v),range=[min(v),max(v)]) for k,v in diff.items()})
            summary[case]=dict(stock=[dict(properties=r['properties'],program_ms=r['timings']['program_ns']/1e6,
                cnf=r['stream'],graph=r['graph']) for r in reference['sides']],modes=results)
    out=dict(cases=summary,paths=len(files),unique=len(set(files.values())),witnesses=collections.Counter(v['status'] for v in witnesses.values()),
             native_release=collections.Counter(r['admission']['native']['path'] for p in rows if p['mode']!='stock' for r in p['sides']))
    (root/'summary.json').write_bytes((json.dumps(out,sort_keys=True,indent=2)+'\n').encode())
    print(out['paths'],out['unique'],out['witnesses'],out['native_release'])
    for k,v in summary.items():
        print(k,[(m,round(t['median']['p1_wall_ms'],1),round(t['median']['search_ms'],1),t['median']['used_derived'],t['median']['actually_reattached'],t['median']['rup_proved']) for m,t in v['modes'].items()])
if __name__=='__main__':run(Path(sys.argv[1]))
