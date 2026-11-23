#!/usr/bin/python3
"""Acquire the old session's provenance in the ordinary per-invocation interpreter."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.environ['INCDEAGLE_FRONT_MODULE'])
from provenance import PROBES, emit, file_record, flags_supported, probe_record

args=sys.argv[1:]
root=Path(os.environ['INCDEAGLE_CPP_RECORD']).parent
slot=root/'compiler-spool'/('c.'+str(os.getpid()))
slot.mkdir(mode=0o700)
cwd=Path.cwd()
gcc='/usr/bin/gcc'
if tuple(args) in PROBES:
    data=sys.stdin.buffer.read()
    result=subprocess.run([gcc,*args],input=data,stdout=subprocess.PIPE)
    (slot/'stdin').write_bytes(data)
    record=probe_record(args,data,result.stdout,result.returncode)
elif flags_supported(args) and (cwd/args[-1]).is_file():
    dep=slot/'deps'
    result=subprocess.run([gcc,'-MD','-MF',str(dep),'-MT','incdeagle',*args],stdout=subprocess.PIPE)
    try:
        legacy,record=file_record(cwd,args,result.stdout,result.returncode,dep)
        emit(root/'cpp.jsonl',legacy)
    except (OSError,ValueError):
        record=dict(kind='unknown',argv=args,errors=['unconfirmed_dependency'])
else:
    emit(root/'frontend-calls.jsonl',dict(kind='unknown',argv=args,errors=['unrecognized_gcc_invocation']))
    legacy=Path(os.environ['INCDEAGLE_FRONT_MODULE']).parent/'stage3/record_gcc.py'
    os.execv(sys.executable,[sys.executable,str(legacy),*args])
(slot/'stdout').write_bytes(result.stdout)
(slot/'argv').write_bytes(b''.join(os.fsencode(a)+b'\0' for a in args))
emit(root/'frontend-calls.jsonl',record)
sys.stdout.buffer.write(result.stdout)
if result.returncode<0:
    import signal
    signo=-result.returncode
    if signo not in (signal.SIGKILL,signal.SIGSTOP):
        signal.signal(signo,signal.SIG_DFL)
    os.kill(os.getpid(),signo)
sys.exit(result.returncode)
