"""Check/build the stage 9 launchers and diagnose tool identities without rebuilding Deagle."""
import ast
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha,read,save
from scripts.stage9.frontend import Toolchain

def main(before,lock,out):
    out.mkdir(parents=True,exist_ok=True)
    rev=lambda d,*a:subprocess.check_output(['git','-C',d,'rev-parse',*a],text=True).strip()
    pin='edd7386f8674eb5db08593d327256ea874bf05f6'
    assert rev(before,'HEAD')==pin
    data=read(lock);known=read(before/'reports/evidence/stage-08/native-build.json')
    for key in ('development_commit','development_parent','development_config'):
        assert data[key]==known[key]
    binary=Path(data['development_binary'])
    assert file_sha(binary)==data['development_sha256']
    assert not subprocess.check_output(['git','-C',binary.parents[2],'status','--porcelain'])
    for tree in (ROOT,before):
        for stage,key in [('deagle-stage5','development'),('deagle-baseline','baseline')]:
            p=tree/'third_party'/stage/'src/cbmc/deagle_exe'
            assert file_sha(p)==read(before/'configs/stage05.lock.json')[key+'_sha256']
    for file in (ROOT/'scripts/stage9').glob('*.py'):ast.parse(file.read_bytes(),filename=str(file))
    subprocess.run(['/bin/sh','-n',str(ROOT/'scripts/stage9/dispatch.sh')],check=True)
    proc=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(ROOT/'scripts/stage9/clock_exec.c'),
                         '-o',str(out/'profile-clock')],capture_output=True,check=True)
    (out/'compiler.log').write_bytes(proc.stdout+proc.stderr)
    sources=['scripts/stage4/session.py','scripts/stage9/dispatch.sh','scripts/stage9/frontend.py',
             'scripts/stage9/provenance.py','scripts/stage9/reference_gcc.py']
    save(out/'environment.json',dict(baseline=pin,stage7=rev(before,'HEAD^'),stage7_data_tree=rev(before,'HEAD:reports/evidence/stage-07'),
        stage8_data_tree=rev(before,'HEAD:reports/evidence/stage-08'),enhanced=known['development_commit'],
        diagnostic_sha256=data['development_sha256'],same_archived_diagnostic=data['development_sha256']==known['development_sha256'],
        sources={n:file_sha(ROOT/n) for n in sources},profile_source=file_sha(ROOT/'scripts/stage9/clock_exec.c'),
        profile_exe=file_sha(out/'profile-clock'),gcc=Toolchain().snapshot(dict(os.environ,LC_ALL='C')),pidfd=hasattr(os,'pidfd_open'),
        affinity=sorted(os.sched_getaffinity(0)),python=platform.python_version(),kernel=platform.release(),
        disk_free=os.statvfs(out).f_bavail*os.statvfs(out).f_frsize,official_api_calls=0))
    print('Python and shell frontends checked, diagnostic C clock built; pinned native binaries verified.',flush=True)
if __name__=='__main__':main(*[Path(s).resolve() for s in sys.argv[1:]])
