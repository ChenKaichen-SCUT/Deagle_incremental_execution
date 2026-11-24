"""Check other safety properties registered for the tasks which actually acquired a new version."""
import argparse
import os
import signal
import subprocess
import time
from pathlib import Path
import yaml
from config import DEAGLE,ROOT,folder
from oracle import metadata,options,read,save,sha
FLAGS={'no-data-race':['--datarace'],'no-overflow':['--signed-overflow-check','--unsigned-overflow-check'],'valid-memsafety':['--pointer-check','--alloc-check','--memory-leak-check']}
def main(root,exe):
    assert sha(exe)==DEAGLE;refs=[]
    for case in sorted((ROOT/'cases/svcomp26/versions').iterdir()):
        task=case.name;m=metadata(task);base=folder(task);spec=yaml.safe_load((base/(task+'.yml')).read_bytes())
        for v in ['P0',*(p.name for p in sorted(case.iterdir()))]:
            src=base/m['input'] if v=='P0' else case/v/'program.i'
            for prop in spec['properties']:
                name=Path(prop['property_file']).stem
                if name not in FLAGS:continue
                d=root/task/v/name;d.mkdir(parents=True,exist_ok=False);(d/'program.i').write_bytes(src.read_bytes())
                argv=[str(exe),*options(m),'--no-assertions',*FLAGS[name],'--trace','--json-ui','program.i']
                t=time.monotonic_ns()
                with (d/'stdout').open('wb') as o,(d/'stderr').open('wb') as e:
                    p=subprocess.Popen(argv,cwd=d,stdout=o,stderr=e,start_new_session=True,env=dict(PATH=os.environ['PATH'],LC_ALL='C',INCDEAGLE_JSON_OUTPUT=str(d/'result.json')))
                    try:rc=p.wait(timeout=120)
                    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait();rc=124
                rows=[];err=[]
                try:
                    doc=read(d/'result.json');rows=[r for obj in doc for r in obj.get('result',[])];err=[obj.get('messageText') for obj in doc if obj.get('messageType')=='ERROR']
                except (ValueError,OSError):pass
                levels={r['property']:r['status'] for r in rows}
                failed=[r for r in rows if r['status']=='FAILURE' and 'unwind' not in r['property']]
                witness=[dict(property=r['property'],reason=r.get('description'),witness_steps=len(r.get('trace',[])),failure_steps=sum(s.get('stepType')=='failure' and s.get('property')==r['property'] for s in r.get('trace',[]))) for r in failed]
                if rc==124:cls='TIMEOUT'
                elif rc not in (0,10):cls='TOOL_FAILURE'
                elif failed:cls='VIOLATION' if any(x['failure_steps'] for x in witness) else 'FAILURE_WITHOUT_MATCHING_TRACE'
                elif any(x!='SUCCESS' for x in levels.values()):cls='UNRESOLVED'
                elif not any('unwind' not in n for n in levels):cls='NO_CHECKABLE_OBLIGATIONS'
                else:cls='BOUNDED_PASS'
                item=dict(task=task,version=v,source_sha256=sha(src),property=name,property_sha256=sha(base/prop['property_file']),registered_P0_expected=prop['expected_verdict'],classification=cls,exit=rc,
                    elapsed_s=(time.monotonic_ns()-t)/1e9,argv=argv,rows=levels,failing=witness,errors=err)
                save(d/'receipt.json',item);refs.append(item);print(task,v,name,cls,flush=True)
    save(root/'summary.json',refs)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);p.add_argument('exe',type=Path);a=p.parse_args();main(a.out.resolve(),a.exe.resolve())
