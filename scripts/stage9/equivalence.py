"""Compare real GCC streams and all seven legacy fields on exactly the same input path."""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import file_sha,read,save
from scripts.stage9 import frontend,provenance

def run(source,pilot,out):
    out.mkdir(parents=True,exist_ok=False)
    work=out/'work';work.mkdir()
    case=source/read(ROOT/'reports/evidence/stage-07/matrix.json')['batch_total']['case_dir']
    for a,b in [('harness.c','harness.c'),('candidate/program.c','program.c')]:
        shutil.copyfile(case/a,work/b)
    generated=sorted(pilot.glob('c.*/unit-source'))
    assert len(generated)==2
    for i,p in enumerate(generated):shutil.copyfile(p,work/f'g{i}.c')
    (work/'nested dir').mkdir()
    (work/'nested dir/a #$.h').write_text('#define UNIT 7\n')
    (work/'complex.c').write_text('#include "nested dir/a #$.h"\nUNIT\n')
    (work/'err.c').write_text('#error intended-stage9-error\n')
    (work/'ghost.c').write_text('#line 1 "missing-evidence.h"\nint n;\n')
    flags=['-E','-D__CPROVER__','-m64','-std=gnu11']
    tests=[('probe-c',list(provenance.PROBES[0]),b'__GNUC__\n'),('probe-cxx',list(provenance.PROBES[1]),b'__cplusplus\n')]
    tests += [(n,flags+[n],b'') for n in ('harness.c','g0.c','g1.c','complex.c','err.c','ghost.c')]
    tests += [('unknown-option',['-E','-P','complex.c'],b'')]
    results=[]
    for label,args,data in tests:
        d=out/label;d.mkdir()
        for name in ('reference','optimized'):(d/name).mkdir()
        stdin=d/'stdin';stdin.write_bytes(data)
        before=d/'reference';after=d/'optimized'
        tools=d/'tools';tools.mkdir()
        env=dict(os.environ,LC_ALL='C')
        receiver=frontend.Candidate(after,tools,env,frontend.Toolchain())
        try:
            for role,argv,options in [(before,[sys.executable,str(ROOT/'scripts/stage3/record_gcc.py'),*args],{}),
                    (after,[str(tools/'optimized/gcc'),*args],receiver.env)]:
                with stdin.open('rb') as si,(role/'stdout').open('wb') as so,(role/'stderr').open('wb') as se:
                    p=subprocess.Popen(argv,cwd=work,env=dict(env,**options,INCDEAGLE_CPP_RECORD=str(role/'cpp.jsonl')),
                                       stdin=si,stdout=so,stderr=se,start_new_session=True)
                    if role==after:
                        until=time.monotonic()+15
                        def remaining():
                            left=until-time.monotonic()
                            if left<=0:raise TimeoutError('equivalence case')
                            return left
                        rc=receiver.wait(p,remaining)
                    else:rc=p.wait(timeout=15)
                    (role/'exit').write_text(str(rc))
        finally:receiver.close()
        same={n:(before/n).read_bytes()==(after/n).read_bytes() for n in ('stdout','stderr','exit')}
        assert all(same.values()),label
        fields=None
        if (before/'cpp.jsonl').exists() and label!='unknown-option':
            a=json.loads((before/'cpp.jsonl').read_bytes());b=json.loads((after/'cpp.jsonl').read_bytes())
            fields={k:a[k]==b[k] for k in a}
            assert len(fields)==7 and all(fields.values()),(label,fields)
        rows=[json.loads(v) for v in (after/'frontend-calls.jsonl').read_bytes().splitlines()]
        errors=[err for r in rows for err in r['errors']]
        assert bool(errors)==(label in ('ghost.c','err.c','unknown-option')),(label,errors)
        results.append(dict(case=label,arguments=args,exit=int((after/'exit').read_text()),identical=same,
            fields=fields,stdout_sha256=file_sha(after/'stdout'),stderr_sha256=file_sha(after/'stderr'),errors=errors))
    save(out/'checks.json',results)
    print('Verified GCC output, diagnostics and status for',len(results),'invocations; all comparable v1 fields equal',flush=True)
if __name__=='__main__':run(*[Path(s).resolve() for s in sys.argv[1:]])
