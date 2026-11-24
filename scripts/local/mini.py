"""Install the pinned repair agent from verified wheels. No model or API call."""
import argparse
import json
import os
import subprocess
import tarfile
import tempfile
import venv
from pathlib import Path

from restore import PROJECT, assert_hash, read


def install(runtime, wheel_tar):
    signed = read(PROJECT/'reports/evidence/stage-01/verified-wheels.json')
    expected = {r['filename']:r['sha256'] for r in signed}
    wheel_dir = runtime/'wheelhouse'
    wheel_dir.mkdir(exist_ok=True)
    venv_dir = runtime/'venv'
    if not (venv_dir/'bin/python').exists():
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    pip = [str(venv_dir/'bin/python'),'-m','pip','--disable-pip-version-check']
    lock = PROJECT/'configs/mini-requirements.lock'
    if wheel_tar:
        with tarfile.open(wheel_tar,'r:') as archive:
            if set(archive.getnames()) != set(expected):
                raise ValueError('wheelhouse file set differs from the release')
            for m in archive:
                if not m.isfile() or Path(m.name).name != m.name:
                    raise ValueError('unexpected wheel name')
                p=wheel_dir/m.name
                if not p.exists():
                    with tempfile.NamedTemporaryFile(dir=wheel_dir,delete=False) as tmp:
                        tmp.write(archive.extractfile(m).read())
                    try:
                        assert_hash(Path(tmp.name),expected[m.name])
                        os.replace(tmp.name,p)
                    finally:
                        Path(tmp.name).unlink(missing_ok=True)
    elif not all((wheel_dir/n).is_file() for n in expected):
        subprocess.run([*pip,'download','--only-binary=:all:','--require-hashes','-r',str(lock),'--dest',str(wheel_dir)],check=True)
    for n,h in expected.items():
        assert_hash(wheel_dir/n,h)
    subprocess.run([*pip,'install','--no-index','--find-links',str(wheel_dir),'--require-hashes','-r',str(lock)],check=True)
    subprocess.run([*pip,'install','--no-index','--no-build-isolation','--no-deps',str(runtime/'mini-swe-agent')],check=True)
    subprocess.run([*pip,'check'],check=True)
    py=str(venv_dir/'bin/python')
    code="import importlib.metadata as m,json;print(json.dumps({k:m.version(k) for k in ('mini-swe-agent','litellm','openai')}))"
    versions=json.loads(subprocess.check_output([py,'-c',code]))
    print(json.dumps({'wheel_hashes_verified':len(expected),'installed':versions},sort_keys=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('runtime',type=Path)
    parser.add_argument('--wheel-tar',type=Path)
    args=parser.parse_args()
    install(args.runtime.resolve(), args.wheel_tar)
