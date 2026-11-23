#!/usr/bin/python3
"""Time the original dependency recorder and its unchanged GCC child in diagnostic runs."""
import json
import os
import runpy
import subprocess
import time
from pathlib import Path
start=time.monotonic_ns()
orig=subprocess.run
system_gcc=0
def run(*a,**kw):
    global system_gcc
    before=time.monotonic_ns()
    try:return orig(*a,**kw)
    finally:system_gcc+=time.monotonic_ns()-before
subprocess.run=run
real_read=Path.read_bytes
read_ns=0
nread=0
def read(self):
    global read_ns,nread
    start=time.monotonic_ns()
    try:return real_read(self)
    finally:read_ns+=time.monotonic_ns()-start;nread+=1
Path.read_bytes=read
try:
    runpy.run_path(os.environ["S8_GCC_ORIGINAL"],run_name="__main__")
finally:
    with (Path(os.environ["S8_OUT"])/"s8-gcc.jsonl").open("a") as f:
        print(json.dumps(dict(pid=os.getpid(),begin=start,end=time.monotonic_ns(),gcc_wall_ns=system_gcc,
               wrapper_file_read_ns=read_ns,read_calls=nread)),file=f)
