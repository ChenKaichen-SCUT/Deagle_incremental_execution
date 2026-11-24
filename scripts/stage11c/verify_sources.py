"""Apply the release patch to a private 11B source tree and check the Linux build fingerprints."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / 'stage11b'))
from instrument import build_sources


def check(tree, evidence):
    locked = {Path(line.split(maxsplit=1)[1].strip()).name: line.split()[0]
              for line in (evidence / 'build.sha256').read_text().splitlines()}
    with tempfile.TemporaryDirectory() as work:
        dest = Path(work)
        build_sources(tree, dest)
        shutil.copyfile(tree / 'minisat-2.2.1/minisat/core/Solver.cc', dest / 'Solver.cc')
        for p in dest.iterdir():
            p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
        subprocess.run(['git','-C',str(dest),'init','--quiet'], check=True)
        patch = (evidence / 'native.patch').resolve()
        for options in (['--check'], []):
            subprocess.run(['git','-C',str(dest),'apply','--whitespace=nowarn',*options,str(patch)], check=True)
        for name in ('trace.hpp','sealed.hpp'):
            shutil.copyfile(HERE / name, dest / name)
        hashes = {}
        for p in sorted(dest.iterdir()):
            if p.is_file() and p.name in locked and p.name != 'native.patch':
                hashes[p.name] = hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
                if hashes[p.name] != locked[p.name]:
                    raise ValueError('generated source differs from measured build: ' + p.name)
        assert set(hashes)=={name for name in locked if name.endswith(('.hpp','.cc','.cpp'))}
        assert hashlib.sha256(patch.read_bytes()).hexdigest()==locked['native.patch']
    return dict(status='MATCH', patch_sha256=locked['native.patch'], generated=hashes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('tree', type=Path, help='prepared stage-10 source tree')
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.tree, args.evidence), indent=2))
