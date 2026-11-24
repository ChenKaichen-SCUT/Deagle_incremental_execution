"""Content-address raw observations without storing the same search stream for every trial."""
from pathlib import Path
import argparse,collections,difflib,gzip,hashlib,io,json,tarfile,zipfile
from witness import result
from gates import decide

def dump(p,v):p.write_bytes((json.dumps(v,sort_keys=True,indent=2)+'\n').encode())
def collect(remote,project,export):
    export.mkdir(parents=True,exist_ok=True)
    out=export/'raw';out.mkdir(exist_ok=True)
    table={};seen=set();measure=[];singles=[];witnesses={}
    with zipfile.ZipFile(out/'objects.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        def keep(p,name):
            if not p.is_file():return
            data=p.read_bytes();idx=hashlib.sha256(data).hexdigest()
            table[name]=idx
            if idx not in seen:
                info=zipfile.ZipInfo(idx);info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,data);seen.add(idx)
        for p in sorted((remote/'formal').glob('*/*/*/pair.json')):
            d=p.parent;key=d.relative_to(remote/'formal').as_posix()
            pair=json.loads(p.read_bytes());sides=[]
            for side in ('old','new'):
                f=d/side
                row=json.loads((f/'receipt.json').read_bytes());sides.append(row)
                if pair['mode']!='stock' and row['exit']==10:
                    wk=(row['source'].get('program.i') or row['source'].get('program.c'))+'-'+hashlib.sha256((f/'answer.txt').read_bytes()).hexdigest()
                    if wk not in witnesses:witnesses[wk]=result(f)
                    row['witness']=wk
                if pair['mode']!='stock':
                    control=json.loads((remote/'formal'/pair['case']/'0/stock'/side/'receipt.json').read_bytes())
                    witness=witnesses.get(row.get('witness'),{'status':'NO_SAT_MODEL'})
                    row['admission']={'native':decide(row,control,witness),'strict_request':decide(row,control,witness,True)}
                for name in ('receipt.json','s8-graph.tsv','s8-input.bin','full_model.json','goto.json','visits.json','sc_input.json','raw_ssa.json','native-bindings.json','bits.tsv','result.json','stdout','stderr','s8-native.tsv','boundary.tsv','answer.txt','events.tsv','plan.txt','diff.json','metrics.json','native-state.tsv','search.bin','harness.c','program.i','program.c'):keep(f/name,'formal/'+key+'/'+side+'/'+name)
                for name in ('stats.tsv','closure-stats.tsv','closure.tsv','native-state.tsv','rup.tsv','original-resident.tsv','retained.tsv','s8-native.tsv','search.bin','learning.bin'):
                    keep(f/'worker'/name,'formal/'+key+'/'+side+'/worker/'+name)
            keep(p,'formal/'+key+'/pair.json')
            for n in ('worker.stdout','worker.stderr','fallback.json'):keep(d/n,'formal/'+key+'/'+n)
            measure.append({**pair,'sides':sides})
        for d in sorted((remote/'singles').glob('*')):
            if not (d/'receipt.json').exists():continue
            singles.append(json.loads((d/'receipt.json').read_bytes()))
            for n in ('receipt.json','stdout','stderr','output.json'):keep(d/n,'singles/'+d.name+'/'+n)
        for top in ('controls','panel-extra'):
            for p in sorted((remote/top).rglob('*')):
                if p.is_file():keep(p,p.relative_to(remote).as_posix())
        for p in sorted((remote/'pilot/lock12').glob('*/*/*/receipt.json')):
            keep(p,p.relative_to(remote).as_posix())
        for n in ('build.sha256','build.log'):keep(remote/'build'/n,'build/'+n)
        for p in sorted((remote/'host').glob('*')):keep(p,'host/'+p.name)
        historical=remote/'diagnostic'
        if historical.is_dir():
            for p in sorted(historical.glob('*/*/*/pair.json')):
                d=p.parent;key=d.relative_to(historical).as_posix()
                for f in ('pair.json','worker.stderr'):
                    keep(d/f,'initial/'+key+'/'+f)
                for side in ('old','new'):
                    for f in ('receipt.json','diff.json','plan.txt','s8-input.bin','s8-graph.tsv','result.json',
                              'worker/native-state.tsv','worker/stats.tsv','worker/closure-stats.tsv','worker/search.bin','worker/retained.tsv'):
                        keep(d/side/f,'initial/'+key+'/'+side+'/'+f)
                    if key=='ticket56/1/GS':
                        for f in ('full_model.json','goto.json','visits.json','native-bindings.json'):
                            keep(d/side/f,'initial/'+key+'/'+side+'/'+f)
            for p in sorted((remote/'initial-build').glob('src/*')):keep(p,'initial-build/src/'+p.name)
            keep(remote/'initial-build/build.sha256','initial-build/build.sha256')
    dump(out/'files.json',table);dump(export/'trials.json',measure);dump(export/'singles.json',singles);dump(export/'witnesses.json',witnesses)
    binary=remote/'build/worker'
    dump(export/'build.json',{'worker_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'inputs':(remote/'build/build.sha256').read_text().splitlines()})
    with (export/'native.patch').open('w') as f:
        for name,base,prefix in [('Closure.cc',remote/'native/minisat-2.2.1/minisat/core','minisat-2.2.1/minisat/core'),
                                 ('ClosureSolver.cc',remote/'native/minisat-2.2.1/minisat/core','minisat-2.2.1/minisat/core'),
                                 ('driver.cpp',project/'scripts/stage10','scripts/stage10'),('epoch.hpp',project/'scripts/stage10','scripts/stage10')]:
            p=prefix+'/'+name
            f.writelines(difflib.unified_diff((base/name).read_text().splitlines(True),(remote/'build/src'/name).read_text().splitlines(True),'a/'+p,'b/'+p))
    print(len(table),'paths',len(seen),'unique',len(measure),'pairs',len(singles),'singles',len(witnesses),'SAT witnesses')
if __name__=='__main__':
    import sys
    collect(*map(Path,sys.argv[1:]))
