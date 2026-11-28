"""Experimental first-root entry for the frozen binary's D4.3 worker ABI."""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(BASE/"scripts"))
from si1b_review_space import check, digest, read, save
from si1b_value_boundary import validate


def publish(lib,native,tools,ctl,cwd,args,elf,seal_hash):
    ready=native/"ready.tsv"
    check(not ready.exists(),"stale native batch")
    data,receipt=validate(lib,native,tools,ctl,cwd,args,elf,seal_hash)
    tmp=native/"diagnostic-ready.tmp"
    with tmp.open("xb") as f:
        f.write(data)
    save(native/"diagnostic-receipt.json",receipt)
    tmp.replace(ready)


if __name__=="__main__":
    lib,native,tools=map(Path,sys.argv[1:])
    reference=BASE/"reports/evidence/si1b-value/frozen/batches.json"
    # The fixed seal index belongs to the reviewed checkout, outside the library passed by the caller.
    check(digest(reference)=="457e559b230f869507d8ca0e600b717c23d4d9e08570b260d17bd45e922addde",
          "changed preregistered batch index")
    lock=read(reference)
    check(digest(BASE/"configs/si1b-value.json")==lock["plan_sha256"] and tools.resolve()==Path(__file__).resolve().parent,
          "unrecognized experimental root worker")
    ctl=read(native/"diagnostic-control.json")
    parent=Path("/proc")/str(os.getppid())
    args=(parent/"cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
    check(Path.cwd()==(parent/"cwd").resolve() and len(args)>1,"invalid live parent")
    check(os.sched_getaffinity(0)=={0} and os.sched_getaffinity(os.getppid())=={0},"unexpected CPU affinity")
    import resource
    expected=read(lib/"seal.json")["limits"]["memory_bytes"]
    check(resource.getrlimit(resource.RLIMIT_AS)==(expected,expected),"unexpected memory limit")
    publish(lib,native,tools,ctl,Path.cwd(),args[1:],digest(parent/"exe"),lock["seals"][ctl["case"]])
