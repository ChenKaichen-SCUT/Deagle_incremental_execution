"""Hash the exact release files under the stage-11C source and evidence paths."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '8de2a0625649254357cd60ede7626204665b5458'
EVIDENCE = ROOT / 'reports/evidence/stage-11c'
MANIFEST = EVIDENCE / 'manifest.json'


def release_paths():
    files = {ROOT / 'reports/stage-11c.md', ROOT / 'project_state.json'}
    for folder in (EVIDENCE, ROOT / 'scripts/stage11c'):
        files.update(p for p in folder.rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts and p != MANIFEST)
    return sorted(files)


def manifest():
    hashes = {}
    for path in release_paths():
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(branch='stage-11c-dynamic-theory-cdcl', parent=BASE,
                status='READY_FOR_REVIEW', algorithm='sha256', sha256=hashes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    expected = manifest()
    if args.write:
        MANIFEST.write_bytes((json.dumps(expected, indent=2, ensure_ascii=False) + '\n').encode())
    if json.loads(MANIFEST.read_bytes()) != expected:
        raise SystemExit('release file set or digest differs from manifest')
    print(f"Verified {len(expected['sha256'])} stage files against the manifest.")
