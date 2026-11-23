"""Collect binary hashes, native Git identities, compiler inputs and solver source differences."""
import hashlib
import difflib
import json
import subprocess
import sys
from pathlib import Path

def capture(work, evidence):
    def git(t,*args):return subprocess.check_output(['git','-C',t,*args])
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    keys=dict(baseline=work/'baseline',enhanced=work/'enhanced')
    original={k:git(t,'rev-parse','HEAD^').decode().strip() for k,t in keys.items()}
    trees={}
    extra=dict(baseline_stream=work/'stream-baseline',enhanced_stream=work/'stream-enhanced',baseline_model=work/'f0-equation')
    if not extra['baseline_model'].exists():extra['baseline_model']=work/'equation'
    for k,t in {**keys,**extra}.items():
        exe=t/'src/cbmc/deagle_exe'
        trees[k]=dict(commit=git(t,'rev-parse','HEAD').decode().strip(),parent=git(t,'rev-parse','HEAD^').decode().strip(),
            tree=git(t,'rev-parse','HEAD^{tree}').decode().strip(),working_changes=git(t,'status','--porcelain','--untracked-files=no').decode(),
            binary_sha256=sha(exe),config_inc_sha256=sha(t/'src/config.inc'))
        assert not trees[k]['working_changes']
    watched=['src/goto-symex/symex_start_thread.cpp','src/goto-symex/memory_model.cpp','src/goto-symex/memory_model_sc.cpp',
             'minisat-2.2.1/minisat/core/Solver.cc','minisat-2.2.1/minisat/core/Closure.cc','minisat-2.2.1/minisat/core/ClosureSolver.cc',
             'src/goto-checker/bmc_util.cpp','src/solvers/sat/satcheck_minisat2.cpp','src/config.inc']
    blobs={}
    for f in watched:
        blobs[f]={}
        for r,t in keys.items():
            obj=original[r]+':'+f
            entry=subprocess.run(['git','-C',t,'rev-parse','--verify',obj],capture_output=True,text=True)
            blobs[f][r]=entry.stdout.strip() if entry.returncode==0 else None
    patch=[]
    for path,versions in blobs.items():
        if versions['baseline']==versions['enhanced']:continue
        left,right=[git(keys[r],'cat-file','blob',versions[r]).decode().splitlines(keepends=True) if versions[r] else [] for r in keys]
        patch.extend(difflib.unified_diff(left,right,'a/'+path,'b/'+path))
    (evidence/'audit/solver-release-sources.diff').write_bytes(''.join(patch).encode())
    binaries={n:sha(p) for n,p in [('codec',evidence/'micro/cache-codec'),('baseline_driver',evidence/'build/driver-baseline/solver-replay'),
                                     ('enhanced_driver',evidence/'build/driver-enhanced/solver-replay')]}
    manifest=dict(diagnostic_worktrees=trees,locked_release_blobs=blobs,drivers=binaries,
                  compiler=subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
                  patches={p.name:sha(p) for p in sorted((evidence/'build').glob('*.patch'))})
    (evidence/'audit/native-provenance.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())

if __name__=='__main__':capture(*map(lambda s:Path(s).resolve(),sys.argv[1:]))
