#!/usr/bin/python3
"""Side probe: time CPU as well as wall time for GCC and its descendants."""
import json
import os
import resource
import runpy
import subprocess
import time
from pathlib import Path

begin=time.monotonic_ns()
cpu_begin=time.process_time_ns()
gcc_wall=gcc_cpu=0
original=subprocess.run
def measured(*a,**kw):
    global gcc_wall,gcc_cpu
    old=resource.getrusage(resource.RUSAGE_CHILDREN)
    t=time.monotonic_ns()
    try:return original(*a,**kw)
    finally:
        gcc_wall+=time.monotonic_ns()-t
        new=resource.getrusage(resource.RUSAGE_CHILDREN)
        gcc_cpu+=round(1e9*((new.ru_utime-old.ru_utime)+(new.ru_stime-old.ru_stime)))
subprocess.run=measured
read=Path.read_bytes
file_ns=0
reads=0
def measured_read(self):
    global file_ns,reads
    t=time.monotonic_ns()
    try:return read(self)
    finally:file_ns+=time.monotonic_ns()-t;reads+=1
Path.read_bytes=measured_read
try:runpy.run_path(os.environ['S8_GCC_ORIGINAL'],run_name='__main__')
finally:
    with (Path(os.environ['S8_OUT'])/'s8-gcc.jsonl').open('a') as f:
        print(json.dumps(dict(begin=begin,end=time.monotonic_ns(),pid=os.getpid(),gcc_wall_ns=gcc_wall,
              gcc_cpu_ns=gcc_cpu,wrapper_cpu_ns=time.process_time_ns()-cpu_begin,wrapper_file_read_ns=file_ns,read_calls=reads)),file=f)
