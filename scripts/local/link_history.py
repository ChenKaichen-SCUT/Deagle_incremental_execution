"""Expose the offline tools at the paths used by the historical stage scripts in a Linux checkout."""
import argparse
from pathlib import Path
import tempfile
from restore import PROJECT, ASSETS, assert_hash, checkout, extract_files, read


def link(target,source):
    if not source.exists():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink() and target.resolve()==source.resolve():
        return
    if target.exists() or target.is_symlink():
        raise ValueError('existing path has a different owner: '+str(target))
    target.symlink_to(source,target_is_directory=source.is_dir())


def optional_sources(runtime,archive):
    assert_hash(archive,read(ASSETS/'lock.json')['local_cache']['tool-sources.tar.gz']['sha256'])
    if (runtime/'historical-sources/complete').exists():
        return
    with tempfile.TemporaryDirectory(dir=runtime) as tmp:
        d=Path(tmp);stage=d/'historical-sources';stage.mkdir()
        extract_files(archive, d/'import', lambda n:n if n.startswith(('conrepair-stage2/','liss-stage2/','yogar-cbmc-inc/')) else None)
        for name in ('liss-stage2','yogar-cbmc-inc'):
            a=d/'import'/name
            checkout(a/'source.pack',a/'refs.json',name,stage/name)
        (d/'import/conrepair-stage2').rename(stage/'conrepair-stage2')
        (stage/'complete').write_text('local historical reference sources\n')
        stage.rename(runtime/'historical-sources')


def bind(project,runtime,extras=None):
    if not (project/'.git').is_dir() or not (project/'scripts/stage11c').is_dir():
        raise ValueError('expected a separate Linux checkout of the research repository')
    for name,src in {'deagle-baseline':'baseline','deagle-work':'stage03','deagle-stage4':'stage04',
                     'deagle-stage5':'stage05','damer-camc':'damer-camc','mini-swe-agent':'mini-swe-agent'}.items():
        link(project/'third_party'/name,runtime/src)
    link(project/'.venv',runtime/'venv')
    link(project/'runs/stage-01/wheels',runtime/'wheelhouse')
    link(project/'runs/stage-07/formal/sources',runtime/'sources')
    link(project/'runs/stage-11b/native',runtime/'native')
    if extras:
        optional_sources(runtime,extras)
        for name in ('liss-stage2','yogar-cbmc-inc','conrepair-stage2'):
            link(project/'third_party'/name,runtime/'historical-sources'/name)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('project',type=Path);ap.add_argument('runtime',type=Path)
    ap.add_argument('--reference-archive',type=Path)
    a=ap.parse_args();bind(a.project.resolve(),a.runtime.resolve(),a.reference_archive)
