"""Reapply the exact patch to its pinned parent in an isolated Git index and regenerate its source files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from instrument import PIN,apply,finish

def git(tree,*args,env=None):
    return subprocess.check_output(['git','-C',tree,*args],env=env)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main(tree,build):
    patch=(build/'native.patch').resolve()
    records={}
    with tempfile.TemporaryDirectory(dir=build) as name:
        scratch=Path(name);index=scratch/'index'
        env=dict(os.environ,GIT_INDEX_FILE=str(index))
        git(tree,'read-tree',PIN,env=env);git(tree,'apply','--cached',str(patch),env=env)
        names=git(tree,'diff','--cached','--name-only',PIN,env=env).decode().splitlines()
        # Regenerate from pristine code independently, including all added headers.
        clone=scratch/'source'
        subprocess.run(['git','clone','--quiet','--shared','--no-checkout',str(tree),str(clone)],check=True)
        git(clone,'read-tree',PIN)
        for n in names:
            blob=git(tree,'rev-parse',':'+n,env=env).decode().strip()
            actual=git(tree,'hash-object','--no-filters',n).decode().strip()
            if blob!=actual:raise ValueError('applied native patch: '+n)
            exists=subprocess.run(['git','-C',tree,'cat-file','-e',PIN+':'+n],capture_output=True).returncode==0
            if exists:git(clone,'checkout-index','--',n)
            records[n]={'git_blob':blob,'sha256':sha(tree/n)}
        (clone/'src/util').mkdir(exist_ok=True)
        apply(clone);finish(clone)
        for n,r in records.items():
            if sha(clone/n)!=r['sha256']:raise ValueError('regenerated native source '+n)
    inspected=['minisat-2.2.1/minisat/core/'+v for v in ('Solver.h','Solver.cc','Closure.h','Closure.cc','ClosureSolver.h','ClosureSolver.cc')]
    inspected+=['src/solvers/sat/satcheck_minisat2.'+x for x in ('h','cpp')]
    inspected+=['src/goto-checker/'+x for x in ('solver_factory.cpp','bmc_util.cpp','theory_lemma.cpp')]
    inspected+=['src/solvers/flattening/'+x for x in ('boolbv.h','boolbv_map.h','boolbv_map.cpp')]
    doc=dict(native_parent=PIN,baseline_project='d02f0e1327fa748be0f76f381c3d9a1fa450e9de',source_files=records,
       inspected_parent_sources={n:hashlib.sha256(git(tree,'show',PIN+':'+n)).hexdigest() for n in inspected},
       compiler=subprocess.check_output(['g++','-dumpfullversion'],text=True).strip(),config=sha(tree/'src/config.inc'),
       binary=sha(tree/'src/cbmc/deagle_exe'),driver=sha(build/'solver-session'),patch=sha(patch),
       project_sources={f.name:sha(f) for f in sorted(HERE.iterdir()) if f.is_file() and f.suffix in ('.py','.sh','.cpp','.h','.hpp','.inc')},
       regenerated_all_sources=True,patch_applies_exactly=True)
    (build/'fingerprint.json').write_bytes((json.dumps(doc,sort_keys=True,indent=2)+'\n').encode())
    print('Verified patch and independently regenerated',len(records),'native files.')
if __name__=='__main__':main(*[Path(p).resolve() for p in sys.argv[1:]])
