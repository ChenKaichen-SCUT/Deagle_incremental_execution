"""Exercise the stage-6 sandbox with its published, frozen input and no provider call."""
import argparse
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from restore import PROJECT, read


def check(project, output):
    evidence=project/'reports/evidence/stage-06'
    index=read(evidence/'archive.json')['files']
    prefix='verification/ai-single-edit/'
    with tempfile.TemporaryDirectory() as tmp,tarfile.open(evidence/'full-runs.tar.gz') as src:
        work=Path(tmp)
        for m in src:
            if not m.name.startswith(prefix):
                continue
            name=m.name[len(prefix):]
            if name not in ('request.json','repair/cex0.json') and not name.startswith('snapshot/'):
                continue
            if not m.isfile():continue
            rel=PurePosixPath(name)
            assert '..' not in rel.parts and not rel.is_absolute()
            blob=src.extractfile(m).read()
            assert hashlib.sha256(blob).hexdigest()==index[m.name]
            f=work/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(blob)
        subprocess.run([str(project/'.venv/bin/python'),'-B',str(project/'scripts/stage6/check_sandbox.py'),str(work),str(output)],check=True)
    record=json.loads(output.read_bytes())
    assert record['provider_calls']==0 and record['native_submit'] and record['native_isolation_preflight']
    print(json.dumps(record,sort_keys=True))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('project',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();check(a.project.resolve(),a.output.resolve())
