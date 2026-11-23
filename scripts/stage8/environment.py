"""Lock a stage 8 run to both release binaries and all nine stage 7 input manifests."""
import datetime
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha,read,save
from scripts.stage7.inputs import validate

BASE='247894bf77904bb34e547b5a636b8afe8527add4'

def git(tree,*args):
    return subprocess.check_output(['git','-C',tree,*args],text=True).strip()

def capture(source,out):
    matrix=read(ROOT/'reports/evidence/stage-07/matrix.json')
    release=read(ROOT/'configs/stage05.lock.json')
    originals={}
    for role,tree,slot in [('baseline','deagle-baseline','baseline'),('enhanced','deagle-stage5','development')]:
        path=ROOT/'third_party'/tree
        sha=file_sha(path/'src/cbmc/deagle_exe')
        rev=git(path,'rev-parse','HEAD')
        dirty=git(path,'status','--porcelain')
        assert not dirty and rev==release[slot+'_commit'] and sha==release[slot+'_sha256']
        originals[role]=dict(commit=rev,source_tree=git(path,'rev-parse','HEAD^{tree}'),sha256=sha,dirty=dirty)
    frozen={}
    for name,item in matrix.items():
        case=validate(source,item)
        gamma=read(case/'gamma.json')
        frozen[name]=dict(files=item['files'],old_cex_sha256=file_sha(source/'fixed-traces'/(name+'.json')),
                          unwind=gamma['semantics']['unwind'],argv=gamma['source_argv']+gamma['verification_output'],limits=gamma['limits'])
    tree=git(ROOT,'rev-parse',BASE+':reports/evidence/stage-07')
    assert git(ROOT,'rev-parse','HEAD:reports/evidence/stage-07')==tree
    result=dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),project_stage7=BASE,working_commit=git(ROOT,'rev-parse','HEAD'),
            worktree_branch=git(ROOT,'branch','--show-current'),originals=originals,frozen=frozen,
            affinity=sorted(os.sched_getaffinity(0)),cpu_model=next(s.split(':',1)[1].strip() for s in Path('/proc/cpuinfo').read_text().splitlines() if s.startswith('model name')),
            memory_total=next(s for s in Path('/proc/meminfo').read_text().splitlines() if s.startswith('MemTotal:')),
            kernel=platform.release(),python=platform.python_version(),gcc=subprocess.check_output(['gcc','-dumpfullversion'],text=True).strip(),
            strace=subprocess.check_output(['strace','-V'],text=True).splitlines()[0],disk_free_bytes=shutil.disk_usage(out.parent).free,
            stage7_frozen_data_tree=tree,cgroup_version=2,official_api_calls=0)
    save(out,result)

if __name__=='__main__':
    capture(*map(lambda s:Path(s).resolve(),sys.argv[1:]))
