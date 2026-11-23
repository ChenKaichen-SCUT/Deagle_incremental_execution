"""Separate microbenchmarks for dependency checks and the two IREP files on frozen pairs."""
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import GotoMap,read,save,file_sha
from scripts.stage4 import change_provider
from scripts.stage8.controller_meter import Recorder

def run(source,codec,out):
    matrix=read(ROOT/'reports/evidence/stage-07/matrix.json')
    out.mkdir(parents=True,exist_ok=True)
    for name in matrix:
        pair=source/'trials'/name/'1/incremental/pair'
        old,front=pair/'old',pair/'frontend'
        manifests=[read(p/'manifest.json') for p in (old,front)]
        known=read(pair/'source-changes.json')
        for rep in range(1,6):
            d=out/name/str(rep); d.mkdir(parents=True,exist_ok=True)
            meter=Recorder()
            with ExitStack() as stack:
                for obj,method,what in [(GotoMap,'__init__','source_and_goto_index'),(change_provider.SequenceMatcher,'get_opcodes','source_diff'),
                                        (change_provider,'read','decode_goto_json'),(change_provider,'compare_mapping','map_correspondence'),
                                        (change_provider,'mutex_calls','sync_and_eligibility')]:
                    meter.hook(stack,obj,method,what)
                with meter.span('changes'):
                    actual=change_provider.changes(old,front,manifests)
            assert actual==known
            save(d/'changes.json',dict(meter.totals))
            for kind,p in [('cache',old/'fragments.irep'),('image',front/'goto.irep')]:
                if not p.is_file():continue
                target=d/(kind+'-reencoded.irep')
                cmd=[str(codec),str(p),str(target)]
                with (d/(kind+'.tsv')).open('wb') as stdout:
                    subprocess.run(cmd,stdout=stdout,check=True)
                save(d/(kind+'.json'),{'source_sha256':file_sha(p),'roundtrip_sha256':file_sha(target),'argv':cmd})


if __name__=='__main__':run(*map(lambda s:Path(s).resolve(),sys.argv[1:]))
