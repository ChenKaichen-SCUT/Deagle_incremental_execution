"""Summarize independent frontend, solver, model and maintenance controls."""
import argparse
import array
import hashlib
import json
import re
import statistics as st
import sys
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import read,file_sha
from scripts.stage8.statistics8 import csvfile,dist,ms,native,search,MODES

def frontend(root):
    groups=defaultdict(list);raw=[]
    for path in sorted((root/'frontend').glob('*/*/*/receipt.json')):
        r=read(path);d=path.parent/'frontend'
        t=native(d)
        row={k:r[k] for k in ('case','variant','repeat','binary_sha256','goto_digest')}
        row.update(outer_ms=ms(r['wait_return_ns']-r['begin_ns']),child_lifetime_ms=ms(r['child_lifetime_wall_ns']),
             wait_tail_ms=ms(r['wait_tail_ns']),popen_ms=ms(r['popen_return_ns']-r['begin_ns']),
             json_kib=r['json_bytes']/1024,irep_kib=r['irep_bytes']/1024)
        if t:
            for k in ('front','preprocess','parse','typecheck','goto_convert','goto_process','goto_json','irep_write'):
                row[k+'_ms']=ms(t[k][1]);row[k+'_cpu_ms']=ms(t[k][2]);row[k+'_calls']=t[k][0]
            row['front_other_ms']=row['front_ms']-sum(row[k+'_ms'] for k in ('preprocess','parse','typecheck','goto_convert'))
            row['native_lifetime_ms']=ms(t['span'][1]-t['span'][0])
            row['lifetime_outside_native_ms']=row['child_lifetime_ms']-row['native_lifetime_ms']
            row['native_other_ms']=row['native_lifetime_ms']-row['front_ms']-row['goto_json_ms']-row['irep_write_ms']
        if (d/'s8-gcc.jsonl').is_file():
            data=[json.loads(x) for x in (d/'s8-gcc.jsonl').read_bytes().splitlines()]
            for new,k in [('system_gcc_wall_ms','gcc_wall_ns'),('system_gcc_cpu_ms','gcc_cpu_ns'),('recorder_cpu_ms','wrapper_cpu_ns'),('dependency_read_ms','wrapper_file_read_ns')]:
                row[new]=ms(sum(z[k] for z in data))
            row['gcc_calls']=len(data)
            row['dependency_file_reads']=sum(z['read_calls'] for z in data)
            row['recorder_script_ms']=ms(sum(z['end']-z['begin'] for z in data))
            row['preprocess_outside_wrapper_ms']=row['preprocess_ms']-row['recorder_script_ms']
        if (d/'cpp.jsonl').is_file():
            cpp=[json.loads(x) for x in (d/'cpp.jsonl').read_bytes().splitlines()]
            row['units']='|'.join(x['unit'] for x in cpp)
            row['n_cpp']=len(cpp)
            row['distinct_cpp_unit']=len({(x['unit'],x['output_sha256']) for x in cpp})
        groups[(r['case'],r['variant'])].append(row);raw.append(row)
    summaries=[];contrasts=[]
    for (case,v),rr in groups.items():
        summaries.append({'case':case,'variant':v,**{k:dist(x[k] for x in rr) for k,val in rr[0].items() if isinstance(val,(int,float)) and k!='repeat'}})
    for name in sorted({k[0] for k in groups}):
        ref={s['repeat']:s for s in groups[name,'recorder']}
        other={s['repeat']:s for s in groups[name,'system-gcc']}
        native_rec={s['repeat']:s for s in groups[name,'native-recorder']}
        native_sys={s['repeat']:s for s in groups[name,'native-system']}
        contrasts.append({'case':name,'recorder_wall_extra_ms':dist(v['outer_ms']-other[i]['outer_ms'] for i,v in ref.items()),
            'recorder_lifetime_extra_ms':dist(v['child_lifetime_ms']-other[i]['child_lifetime_ms'] for i,v in ref.items()),
            'recorder_native_cpp_extra_ms':dist(v['preprocess_ms']-native_sys[i]['preprocess_ms'] for i,v in native_rec.items()),
            'first_ms':ref[1]['outer_ms'],'subsequent_median_ms':st.median(s['outer_ms'] for i,s in ref.items() if i>1)})
    return raw,{'groups':summaries,'matched':contrasts}

def core_records(path):
    words=array.array('I')
    with path.open('rb') as f:words.fromfile(f,path.stat().st_size//4)
    if sys.byteorder!='little':words.byteswap()
    i=0
    while i<len(words):
        kind=words[i];i+=1
        if kind==0xfffffff0:
            n=words[i];i+=1
            yield 'clause',words[i:i+n];i+=n
        elif kind==0xfffffff1:
            yield 'variable',words[i:i+3];i+=3
        elif kind==0xfffffff2:yield 'graph',()
        elif kind==0xfffffff3:
            n=words[i];i+=1;yield 'assumptions',words[i:i+n];i+=n
        elif kind==0xfffffff4:
            yield 'polarity',words[i:i+2];i+=2
        else:raise ValueError('Unknown raw record')
    assert i==len(words)

def compare_streams(a,b):
    import itertools
    match=file_sha(a)==file_sha(b)
    result={'sha256':[file_sha(a),file_sha(b)],'bytes':[a.stat().st_size,b.stat().st_size],'equal':match}
    counts=[Counter(),Counter()]
    order=[hashlib.sha256(),hashlib.sha256()]
    prefix=[None,None];first=None
    for i,(x,y) in enumerate(itertools.zip_longest(core_records(a),core_records(b))):
        for k,v in enumerate((x,y)):
            if v is None:continue
            counts[k][v[0]]+=1
            if v[0]=='variable':order[k].update(v[1].tobytes())
        if first is None and x!=y:
            first={'record_index_zero_based':i,'clause_counts_so_far':[z['clause'] for z in counts],
                'left':None if x is None else [x[0],list(x[1])[:32]],'right':None if y is None else [y[0],list(y[1])[:32]]}
    result.update(counts=list(map(dict,counts)),variable_stream_sha256=[h.hexdigest() for h in order],first=first)
    def clauses(p):
        return (value for tag,value in core_records(p) if tag=='clause')
    imbalance=Counter()
    unordered=Counter()
    first_clause=None
    changed=0
    for i,(x,y) in enumerate(itertools.zip_longest(clauses(a),clauses(b))):
        if x==y:continue
        changed+=1
        if first_clause is None:
            first_clause={'index_zero_based':i,'left':None if x is None else list(x),'right':None if y is None else list(y)}
        for value,sign in ((x,1),(y,-1)):
            if value is None:continue
            imbalance[tuple(value)]+=sign
            unordered[tuple(sorted(value))]+=sign
    result['signed_clauses']={'different_sequence_positions':changed,'first':first_clause,
        'same_multiset_ordered_literals':not any(imbalance.values()),'same_multiset_ignoring_literal_order':not any(unordered.values()),
        'unmatched_clauses_each_side_ignoring_literal_order':[sum(v for v in unordered.values() if v>0),-sum(v for v in unordered.values() if v<0)]}
    return result

def first_diff(a,b):
    aa=a.read_bytes().splitlines();bb=b.read_bytes().splitlines()
    first=next((i for i,(x,y) in enumerate(zip(aa,bb)) if x!=y),min(len(aa),len(bb)) if len(aa)!=len(bb) else None)
    return {'length':[len(aa),len(bb)],'same_order':aa==bb,'same_multiset':Counter(aa)==Counter(bb),'first_index':first,
            'example':None if first is None else [(z[first][:260].decode('utf8','replace') if first<len(z) else None) for z in (aa,bb)]}
def comparison(a,b):
    return {'cnf_and_variables':compare_streams(a/'s8-input.bin',b/'s8-input.bin'),'graph_and_guard_order':first_diff(a/'s8-graph.tsv',b/'s8-graph.tsv'),
            'early_search':first_diff(a/'s8-trace.tsv',b/'s8-trace.tsv') if (a/'s8-trace.tsv').exists() and (b/'s8-trace.tsv').exists() else None}

def printed_equation(directory):
    msg=(directory/'diagnostic.stdout').read_bytes().replace(b'\r\n',b'\n')
    blocks=msg.split(b'see the equation!\n',1)[1].split(b'finish seeing!',1)[0]
    return [b.strip() for b in blocks.split(b'--------------\n') if b.strip()]

def equation_difference(a,b):
    x,y=printed_equation(a),printed_equation(b)
    diff=[i for i,(p,q) in enumerate(zip(x,y)) if p!=q]
    tls=re.compile(rb'(?m)^__CPROVER_(?:thread_key_dtors|rounding_mode|thread_id)!\d+#1 = (?:array_of\(NULL\)|0)$')
    return {'blocks':[len(x),len(y)],'row_multiset_identical':Counter(x)==Counter(y),'different_positions':len(diff),
            'only_tls_initializers_differ':len(x)==len(y) and bool(diff) and all(tls.search(x[i]) and tls.search(y[i]) for i in diff),
            'first':None if not diff else {'position_zero_based':diff[0],'original':x[diff[0]].decode(),'enhanced':y[diff[0]].decode()}}

def old_and_solver(root):
    rows=[];old=[]
    for d in sorted((root/'old-controls').glob('*/*/receipt.json')):
        r=read(d);s=search(d.parent)
        old.append(dict(repeat=r['repeat'],mode=r['mode'],solver_ms=1000*r['timings']['Solver'],trace_steps=r['trace_steps'],**s))
    for mode in ('baseline','development','development-observed'):
        ss=[r for r in old if r['mode']==mode]
        rows.append({'mode':mode,**{k:dist(r.get(k) for r in ss) for k in ('solver_ms','trace_steps','decisions','conflicts','propagations','theory_propagations','theory_cycles','model_variables','model_clauses')}})
    result={'original_old_controls':rows}
    ordered=root/'side/ordered/airline_reservations_6/old/1'
    result['old_inputs']=comparison(ordered/'baseline-on',ordered/'development-on')
    result['printed_old_equation']=equation_difference(ordered/'baseline-on',ordered/'development-on')
    fib=root/'side/ordered-fib/fib_updates_8/01/on'
    result['fibonacci_preimport']=comparison(fib/'I2/pair/candidate',fib/'I3/pair/candidate')
    crossed=[]
    for p in (root/'replay/trials').glob('*/*/receipt.json'):
        crossed.append(read(p))
    result['cross_controls']=[]
    if crossed:
        for a in ('baseline','enhanced'):
            for b in ('baseline','enhanced'):
                ss=[r for r in crossed if r['input']==a and r['solver']==b]
                result['cross_controls'].append({'input':a,'solver':b,'matching_searches':sum(r['exact_search_reproduction'] for r in ss),
                    'solver_ms':dist(ms(r['solve_wall_ns']) for r in ss),'conflicts':dist(r['conflicts'] for r in ss),
                    'decisions':dist(r['decisions'] for r in ss),'propagations':dist(r['propagations'] for r in ss)})
        d=root/'replay/captures'
        result['replayed_inputs']=comparison(d/'baseline',d/'enhanced')
    return old,result

def micro(root):
    output=[]
    for p in (root/'micro').glob('*/*/changes.json'):
        row={'case':p.parents[1].name,'repeat':int(p.parent.name)}
        for name,v in read(p).items():row['diff_'+name.split('.')[-1]+'_exclusive_ms']=ms(v[3])
        for kind in ('image','cache'):
            file=p.with_name(kind+'.tsv')
            if not file.exists():continue
            for line in file.read_text().splitlines():
                op,x,y=line.split('\t')
                if op=='bytes':row[kind+'_bytes']=int(x)
                else:row[kind+'_'+op+'_ms']=ms(int(x));row[kind+'_'+op+'_cpu_ms']=ms(int(y))
        output.append(row)
    return sorted(output,key=lambda r:(r['case'],r['repeat']))

def setup(root):
    rows=[]
    by_case=defaultdict(dict)
    for path in sorted((root/'frontend-setup').glob('*/*/*/receipt.json')):
        r=read(path)
        row={k:r[k] for k in ('case','variant','repeat','goto_digest','binary_sha256')}
        row['child_ms']=ms(r['child_wall_ns'])
        by_case[r['case']][r['repeat'],r['variant']]=row['child_ms']
        rows.append(row)
    summaries={}
    for c,values in sorted(by_case.items()):
        summaries[c]={v:dist(values[i,v] for i in range(1,6)) for v in ('none','stdin','source','both')}
        for left,right in [('none','stdin'),('none','source'),('source','both'),('none','both')]:
            summaries[c][right+'_minus_'+left]=dist(values[i,right]-values[i,left] for i in range(1,6))
    if len(rows)!=100:raise ValueError('Incomplete isolated compiler controls')
    return rows,summaries

def overhead(root,formal_rows):
    data=[]
    for case in sorted({r['case'] for r in formal_rows}):
        for mode in MODES:
            vals={(r['rep'],r['detail']):r['wall_ms'] for r in formal_rows if r['case']==case and r['mode']==mode}
            deltas=[vals[n,True]-vals[n,False] for n in range(1,6)]
            data.append({'case':case,'mode':mode,'scope':'formal-paired' if mode!='F0' else 'original-off_vs_instrumented-on',
                         'wall_difference_ms':dist(deltas),'relative_pct':dist(100*(vals[n,True]/vals[n,False]-1) for n in range(1,6))})
    separate=defaultdict(dict)
    for f in (root/'side/baseline-meter').glob('*/*/*/*/receipt.json'):
        r=read(f);separate[r['case']][r['repeat'],r['detail']]=r
    for case,vals in sorted(separate.items()):
        data.append({'case':case,'mode':'F0','scope':'same_diagnostic_binary_separate_outer_service',
            'wall_difference_ms':dist(ms(vals[n,True]['wall_ns']-vals[n,False]['wall_ns']) for n in range(1,6)),
            'relative_pct':dist(100*(vals[n,True]['wall_ns']/vals[n,False]['wall_ns']-1) for n in range(1,6))})
    return data

def run(root,dest):
    import csv
    rows=[]
    with (dest/'ablation-results.csv').open(encoding='utf8') as f:
        for row in csv.DictReader(f):
            rows.append({'case':row['case'],'mode':row['mode'],'rep':int(row['rep']),'detail':row['detail']=='True','wall_ms':float(row['wall_ms'])})
    fram,front=frontend(root)
    setup_rows,front['configuration_controls']=setup(root)
    csvfile(dest/'frontend-setup.csv',setup_rows)
    old,solver=old_and_solver(root)
    micros=micro(root)
    csvfile(dest/'frontend-results.csv',fram);csvfile(dest/'old-search.csv',old);csvfile(dest/'maintenance-micro.csv',micros)
    for name,doc in [('frontend',front),('solver',solver),('diagnostic-overhead',overhead(root,rows))]:
        (dest/(name+'.json')).write_bytes((json.dumps(doc,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode())
    print('Independent frontend rows',len(fram),'old controls',len(old),'maintenance rows',len(micros),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('raw',type=Path);p.add_argument('export',type=Path)
    a=p.parse_args();run(a.raw,a.export)
