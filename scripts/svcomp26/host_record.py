"""Record public machine, binary and native filesystem timestamps before the content archive discards mtimes."""
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
from oracle import read,save,sha
from config import ROOT,TASKS
def record(root,exe,driver):
    def shell(*cmd):return subprocess.check_output(cmd,text=True).strip()
    cg=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
    def utc(ns):return datetime.fromtimestamp(ns/1e9,tz=timezone.utc).isoformat()
    clock={}
    for task in TASKS:
        p=root/'P0'/task/'program.i'
        if not p.exists():continue
        versions=sorted((root/'oracles'/task).glob('P*/receipt.json'))
        models=sorted((root/'rounds'/task).glob('P*/controller.json'))
        if not models:continue
        start=p.stat().st_mtime_ns;end=max(f.stat().st_mtime_ns for f in [*versions,*models])
        clock[task]=dict(start_utc=utc(start),end_utc=utc(end),calendar_s=(end-start)/1e9,scope='from P0 input preparation to final independent property receipt or last failed generation; includes batch queue and review')
    save(root/'machine.json',dict(kernel=platform.release(),arch=platform.machine(),machine_cpu=next(l.partition(':')[2].strip() for l in Path('/proc/cpuinfo').read_text().splitlines() if l.startswith('model name')),
       affinity=sorted(os.sched_getaffinity(0)),memtotal=Path('/proc/meminfo').read_text().splitlines()[0],cgroup_memory=(cg/'memory.max').read_text().strip(),
       gcc=shell('gcc','-dumpfullversion'),python=platform.python_version(),disk_free_bytes=shutil.disk_usage(root).free,
       deagle=sha(exe),worker=sha(driver),calendar=clock))
if __name__=='__main__':record(*[Path(s).resolve() for s in sys.argv[1:]])
