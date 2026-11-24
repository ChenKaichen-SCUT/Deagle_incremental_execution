"""Independent replay for the nominated program whose only registered property is no-data-race."""
import os
import subprocess
import sys
import time
from pathlib import Path
import yaml
from config import DEAGLE,folder
from oracle import save,sha,read
exe,out=map(lambda s:Path(s).resolve(),sys.argv[1:]);assert sha(exe)==DEAGLE
task='workstealqueue_mutex-1';base=folder(task);y=base/(task+'.yml');spec=yaml.safe_load(y.read_bytes())
prop=spec['properties'];assert len(prop)==1 and prop[0]['property_file'].endswith('no-data-race.prp')
out.mkdir(parents=True,exist_ok=False);source=base/spec['input_files'];(out/'program.i').write_bytes(source.read_bytes())
bits={'ILP32':'--32','LP64':'--64'}[spec['options']['data_model']]
argv=[str(exe),'--function','main','--deagle-closure','--mm','sc',bits,'--no-assertions','--datarace','--unwind','8','--unwinding-assertions','--trace','--json-ui','program.i']
start=time.monotonic_ns()
with (out/'stdout').open('wb') as o,(out/'stderr').open('wb') as e:
    try:
        rc=subprocess.run(argv,cwd=out,stdout=o,stderr=e,env=dict(PATH=os.environ['PATH'],LC_ALL='C',INCDEAGLE_JSON_OUTPUT=str(out/'result.json')),timeout=120).returncode
    except subprocess.TimeoutExpired:rc=124
try:
    js=read(out/'result.json');rows={k['property']:k['status'] for m in js for k in m.get('result',[])}
    errors=[m.get('messageText') for m in js if m.get('messageType')=='ERROR']
except (OSError,ValueError):rows={};errors=[]
save(out/'receipt.json',dict(task=task,scope='no-data-race only; excluded from reachability',argv=argv,
 exit=rc,elapsed_ns=time.monotonic_ns()-start,input_sha256=sha(source),yaml_sha256=sha(y),property_sha256=sha(base/prop[0]['property_file']),
 data_model=spec['options']['data_model'],property_rows=rows,errors=errors))
