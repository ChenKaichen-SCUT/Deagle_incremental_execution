"""Export the complete pinned Deagle source and the actual generated 11C worker for browsing/building."""
import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from restore import PROJECT, assert_hash, git, read


def export(runtime, built, target):
    native=runtime/'native'
    lock=read(PROJECT/'runtime/local/deagle-refs.json')['refs']['native']
    assert git(native,'rev-parse','HEAD')==lock['commit']
    target.mkdir(parents=True,exist_ok=False)
    # Only tracked files are admitted from the base tree, including its original notices.
    with tempfile.TemporaryFile() as f:
        subprocess.run(['git','-C',native,'archive','HEAD'],check=True,stdout=f)
        f.seek(0)
        subprocess.run(['tar','-xf','-','-C',target],stdin=f,check=True)
    # Apply the same source patch audited in stage 10, including four new source includes.
    patch=PROJECT/'reports/evidence/stage-10/native.patch'
    subprocess.run(['git','-C',target,'init','-q','-b','native-source-11c'],check=True)
    git(target,'apply','--whitespace=nowarn','--check',str(patch))
    git(target,'apply','--whitespace=nowarn',str(patch))
    for s in git(native,'diff','--name-only','HEAD').splitlines():
        assert_hash(target/s,hashlib.sha256((native/s).read_bytes()).hexdigest())
    for name in ('stage10_bridge.inc','stage10_hooks.h','stage10_native_stats.inc','stage10_telemetry.h'):
        assert_hash(target/'src/util'/name,hashlib.sha256((native/'src/util'/name).read_bytes()).hexdigest())
    shutil.copyfile(native/'src/config.inc',target/'src/config.inc')
    worker=target/'worker-11c';worker.mkdir()
    locked={Path(n.strip()).name:h for h,n in (line.split(maxsplit=1) for line in
           (PROJECT/'reports/evidence/stage-11c/build.sha256').read_text().splitlines())}
    for n in sorted(locked):
        if n.endswith(('.hpp','.cc','.cpp')):
            assert_hash(built/'src'/n,locked[n])
            shutil.copyfile(built/'src'/n,worker/n)
    for n in ('rupcheck.cpp','native_contract.cpp','co_control.cpp'):
        shutil.copyfile(PROJECT/'scripts/stage11c'/n,worker/n)
    shutil.copyfile(PROJECT/'scripts/local/standalone-worker.sh',worker/'build.sh')
    (worker/'build.sh').chmod(0o755)
    shutil.copyfile(PROJECT/'scripts/local/native-source.md',target/'LOCAL-11C.md')
    # Keep the public source branch independent of the upstream repository's shallow boundary.
    git(target,'add','--all','--','.')
    base_files=subprocess.check_output(['git','-C',native,'ls-tree','-rz','--name-only','HEAD'])
    git(target,'--literal-pathspecs','add','-f','--pathspec-from-file=-','--pathspec-file-nul',input=base_files)
    git(target,'add','-f','--','src/config.inc','worker-11c')
    for n in ('stage10_bridge.inc','stage10_hooks.h','stage10_native_stats.inc','stage10_telemetry.h'):
        git(target,'add','-f','--','src/util/'+n)
    # Use the project's existing authorship and a stable timestamp for a reproducible source commit.
    source_commit='7d2d08ecbf6e643d3537131489ab6ba23c327c52'
    def identity(fmt):
        return subprocess.check_output(['git','-c','safe.directory='+str(PROJECT),'-C',PROJECT,
                                       'show','-s','--format='+fmt,source_commit],text=True).strip()
    env=dict(os.environ)
    for k in ('AUTHOR','COMMITTER'):
        for field,fmt in [('NAME','%an'),('EMAIL','%ae'),('DATE','%aI')]:
            env['GIT_'+k+'_'+field]=identity(fmt)
    git(target,'commit','-q','-m','Publish complete native Deagle source and verified 11C worker',env=env)
    print(git(target,'rev-parse','HEAD'),git(target,'rev-parse','HEAD^{tree}'))


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for arg in ('runtime','build','target'):
        ap.add_argument(arg,type=Path)
    a=ap.parse_args()
    export(a.runtime.resolve(),a.build.resolve(),a.target.resolve())
