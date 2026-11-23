"""Run the released certificate binder with nested timings in a separate Python process."""
import json
import sys
from contextlib import ExitStack
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from incdeagle.theory import cache,context
from scripts.stage8.controller_meter import Recorder

if __name__=="__main__":
    assert sys.argv[1]=="bind"
    dest=Path(sys.argv[2])
    meter=Recorder()
    meter.phase="binding"
    with ExitStack() as stack:
        for obj,name,what in [(cache,"read","json_read"),(context,"read","json_read"),(cache,"save","json_write"),
            (cache,"digest","hash"),(context,"digest","hash"),(cache,"freeze","context_build"),(cache,"check","cert_check"),
            (cache,"validate","eligibility"),(context.Registry,"bind","literal_bind")]:
            meter.hook(stack,obj,name,what)
        with meter.span("binder"):
            cache.bind(dest)
    (dest/"s8-binder.json").write_text(json.dumps(meter.totals))
