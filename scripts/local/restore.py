"""Restore the frozen native worktrees and executable inputs on Linux, without network access."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[2]
ASSETS = PROJECT / 'runtime/local'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def git(target, *args, **kwargs):
    return subprocess.run(['git', '-C', str(target), *args], check=True,
                          stdout=subprocess.PIPE, **kwargs).stdout.decode().strip()


def checkout(pack, metadata, name, target):
    meta = read(metadata)
    if sha(pack) != meta['pack_sha256']:
        raise ValueError('Git object pack hash mismatch')
    record = meta['refs'][name]
    if not all(re.fullmatch('[0-9a-f]{40}', k) for k in
               [record['commit'],record['tree'],*meta['shallow']]):
        raise ValueError('invalid repository identity')
    target.mkdir()
    git(target, 'init', '-q')
    with pack.open('rb') as f:
        git(target, 'index-pack', '--stdin', stdin=f)
    if meta['shallow']:
        (target/'.git/shallow').write_text('\n'.join(meta['shallow'])+'\n')
    for k, item in meta['refs'].items():
        git(target, 'update-ref', 'refs/heads/frozen/'+k, item['commit'])
    git(target, 'checkout', '--quiet', '--detach', record['commit'])
    git(target, 'fsck', '--full', '--no-dangling')
    assert git(target, 'rev-parse', 'HEAD^{tree}') == record['tree']


def extract_files(archive, dest, rename=lambda n: n):
    """Copy regular files only. Refuse aliases, traversal and symlink parents."""
    with tarfile.open(archive, 'r:*') as source:
        for member in source:
            if member.isdir():
                continue
            name = rename(member.name)
            if name is None:
                continue
            path = PurePosixPath(name)
            if not member.isfile() or path.is_absolute() or '..' in path.parts or '\\' in name:
                raise ValueError('unexpected archive entry')
            target = dest.joinpath(*path.parts)
            if target.resolve() != target or dest.resolve() not in target.parents:
                raise ValueError('non-local extraction path')
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(member) as f, target.open('wb') as out:
                shutil.copyfileobj(f, out)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def assert_hash(path, expected):
    if sha(path) != expected:
        raise ValueError('hash mismatch: ' + str(path))


def verify(root):
    lock = read(ASSETS/'lock.json')
    for name, item in lock['public'].items():
        assert_hash(ASSETS/name,item['sha256'])
    refs = read(ASSETS/'deagle-refs.json')['refs']
    for name, item in refs.items():
        assert git(root/name,'rev-parse','HEAD') == item['commit']
    for name in ('damer-camc','mini-swe-agent'):
        assert git(root/name,'rev-parse','HEAD') == read(ASSETS/name/'refs.json')['refs'][name]['commit']
    native = read(PROJECT/'reports/evidence/stage-10/fingerprint.json')
    assert_hash(root/'native/src/cbmc/deagle_exe',native['binary'])
    assert_hash(root/'native/src/config.inc',native['config'])
    assert_hash(root/'baseline/src/cbmc/deagle_exe',read(PROJECT/'configs/stage05.lock.json')['baseline_sha256'])
    c11 = dict((Path(n.strip()).name,h) for h,n in (line.split(maxsplit=1) for line in
               (PROJECT/'reports/evidence/stage-11c/build.sha256').read_text().splitlines()))
    for relative in ('native/src/util/util.a','native/src/solvers/solvers.a','11c/worker','11c/native-contract','11c/rupcheck'):
        assert_hash(root/relative,c11[Path(relative).name])
    members = read(ASSETS/'thin-members.json')
    listed=set()
    for lib in ('native/src/util/util.a','native/src/solvers/solvers.a'):
        archive=(root/lib).resolve()
        for n in subprocess.check_output(['ar','t',archive], text=True).splitlines():
            listed.add((archive.parent/n).resolve().relative_to(root.resolve()).as_posix())
    if listed != set(members):
        raise ValueError('thin archive member list differs from release')
    for name,h in members.items():
        assert_hash(root/name,h)
    for stage in ('03','04','05'):
        assert_hash(root/('stage'+stage)/'src/cbmc/deagle_exe',
                    read(PROJECT/('configs/stage'+stage+'.lock.json'))['development_sha256'])
    src = read(PROJECT/'reports/evidence/stage-07/archive.json')['files']
    for n,h in src.items():
        if n.startswith('sources/'):
            assert_hash(root/n,h)
    return {'deagle_commits':{k:v['commit'] for k,v in refs.items()},'native_frontend':native['binary'],
            'frozen_worker':c11['worker'],'source_files':sum(n.startswith('sources/') for n in src)}


def restore(dest):
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if not (dest/'restored.json').is_file():
            raise ValueError('choose a new directory or an existing completed runtime')
        verify(dest)
        return
    for n,v in read(ASSETS/'lock.json')['public'].items():
        assert_hash(ASSETS/n,v['sha256'])
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        d=Path(tmp)/'runtime'
        d.mkdir()
        for name in read(ASSETS/'deagle-refs.json')['refs']:
            checkout(ASSETS/'deagle-stages.pack',ASSETS/'deagle-refs.json',name,d/name)
        for name in ('damer-camc','mini-swe-agent'):
            checkout(ASSETS/name/'source.pack',ASSETS/name/'refs.json',name,d/name)
        def legacy(n):
            if n.startswith('damer/'):
                return 'damer-camc/build/'+n.split('/',1)[1]
            if n.startswith('sources/'):
                return n
            stage,filename=n.split('/',1)
            if stage not in ('stage03','stage04','stage05') or filename!='deagle_exe':
                raise ValueError('unexpected historical binary')
            return stage+'/src/cbmc/'+filename
        extract_files(ASSETS/'stage10-prebuilt.tar.gz',d,
                      lambda n:'baseline/src/cbmc/deagle_exe' if n=='baseline/deagle_exe' else n)
        extract_files(ASSETS/'thin-members.tar.gz',d)
        extract_files(ASSETS/'stage11c-binaries.tar.gz',d)
        extract_files(ASSETS/'legacy-tools.tar.gz',d,legacy)
        stamp=verify(d)
        (d/'restored.json').write_text(json.dumps(stamp,indent=2)+'\n')
        d.rename(dest)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('dest',type=Path)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.check:
        print(json.dumps(verify(args.dest.resolve()),sort_keys=True))
    else:
        restore(args.dest)
        print('Verified local native runtime in',args.dest.resolve())
