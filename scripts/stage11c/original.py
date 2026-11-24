"""Time the frozen F0 Deagle binary directly, using the exact six full-program inputs."""
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from audit import digest, read, save

BASE_SHA = '4566c4ae50aed3be4d68aa5450a049952b32daad88b3ac745efb72e839a318a3'
BASE_COMMIT = 'a159f9923722646185ba8028610b2eef2618fa72'


def run(formal, exe, out):
    assert digest(exe) == BASE_SHA
    out.mkdir(parents=True,exist_ok=True)
    cases = sorted(p.parents[2].name for p in formal.glob('*/0/stock/pair.json'))
    assert len(cases) == 3
    results = []
    stored = set()
    with tempfile.TemporaryDirectory(dir=out) as tmp, zipfile.ZipFile(out/'original-outputs.zip','w',zipfile.ZIP_DEFLATED) as log:
        wd = Path(tmp)
        for rep in range(1,8):
            for case in cases if rep%2 else reversed(cases):
                for side in ('old','new'):
                    orig = formal/case/'0/stock'/side
                    expected = read(orig/'receipt.json')
                    job = wd/case/side
                    job.mkdir(parents=True,exist_ok=True)
                    for name,sha in expected['source'].items():
                        dst = job/name
                        shutil.copyfile(orig/name,dst)
                        assert digest(dst) == sha
                    dest = job/f'result-{rep}.json'
                    env = dict(PATH=os.environ['PATH'],LC_ALL='C',INCDEAGLE_JSON_OUTPUT=str(dest))
                    start = time.monotonic_ns()
                    proc = subprocess.run([str(exe),*expected['argv']],cwd=job,env=env,
                                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180)
                    elapsed = time.monotonic_ns()-start
                    raw = dest.read_bytes()
                    properties = [(i['property'],i['status']) for obj in json.loads(raw) for i in obj.get('result',[])]
                    assert proc.returncode == expected['exit'] and properties == [(p,s) for p,s,_ in expected['properties']]
                    objects = {}
                    for name,data in [('stdout',proc.stdout),('stderr',proc.stderr),('result.json',raw)]:
                        sha = hashlib.sha256(data).hexdigest()
                        if sha not in stored:
                            log.writestr(sha,data)
                            stored.add(sha)
                        objects[name] = sha
                    results.append(dict(case=case,side=side,trial=rep,source=expected['source'],argv=expected['argv'],
                                        exit=proc.returncode,properties=properties,wall_ns=elapsed,objects=objects))
            print('F0',rep,'of 7',flush=True)
    med = {case:{side:statistics.median(r['wall_ns'] for r in results if r['case']==case and r['side']==side)/1e6
                 for side in ('old','new')} for case in cases}
    save(out,'original.json',dict(commit=BASE_COMMIT,binary_sha256=BASE_SHA,rows=results,program_median_ms=med,
                                  raw_sha256=digest(out/'original-outputs.zip')))
    print(med)

if __name__ == '__main__':
    run(*[Path(x).resolve() for x in sys.argv[1:]])
