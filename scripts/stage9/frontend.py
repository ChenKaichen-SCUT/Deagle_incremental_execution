"""Linux candidate frontend. GCC executes with the same cwd, standard streams and environment."""
import errno
import hashlib
import math
import os
import select
import shutil
import subprocess
import time
from pathlib import Path

from incdeagle.model.identity import digest, read, save
from scripts.stage9 import provenance as proof

MODULE=Path(__file__).resolve().parent
ENV_KEYS=('CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','OBJC_INCLUDE_PATH','GCC_EXEC_PREFIX',
          'COMPILER_PATH','LIBRARY_PATH','GCC_COMPARE_DEBUG','SOURCE_DATE_EPOCH','GCC_COLORS',
          'DEPENDENCIES_OUTPUT','SUNPRO_DEPENDENCIES','LANG','LANGUAGE','LC_ALL','LC_CTYPE','LC_MESSAGES',
          'LD_LIBRARY_PATH','LD_PRELOAD','POSIXLY_CORRECT')
UNSUPPORTED_ENV={'GCC_EXEC_PREFIX','COMPILER_PATH','DEPENDENCIES_OUTPUT','SUNPRO_DEPENDENCIES',
                 'LD_PRELOAD','GCC_COMPARE_DEBUG'}


class Toolchain:
    def __init__(self):
        self.cache={}

    def snapshot(self,env,remaining=None):
        driver=Path('/usr/bin/gcc')
        def query(arg):
            timeout=min(5,remaining()) if remaining else 5
            return subprocess.check_output([driver,arg],env=env,timeout=timeout,stderr=subprocess.PIPE).strip()
        def binary(path):
            real=path.resolve(strict=True)
            key=(real,proof.stamp(real))
            if key not in self.cache:
                h=hashlib.sha256()
                with real.open('rb') as f:
                    for block in iter(lambda:f.read(1048576),b''):
                        h.update(block)
                value=h.hexdigest()
                if proof.stamp(real)!=key[1]:
                    raise ValueError('compiler_changed_while_hashing')
                self.cache[key]=value
            return [str(real),self.cache[key]]
        info={'environment':{k:proof.sha(os.fsencode(env[k])) for k in ENV_KEYS if k in env}}
        errors=['unsupported_compiler_environment:'+k for k in sorted(UNSUPPORTED_ENV & env.keys())]
        try:
            info['driver']=binary(driver)
            info['version']=os.fsdecode(query('-dumpfullversion'))
            info['specs_sha256']=proof.sha(query('-dumpspecs'))
            for name in ('cc1','cc1plus'):
                path=Path(os.fsdecode(query('-print-prog-name='+name)))
                if not path.is_absolute():
                    raise ValueError('unresolved_compiler_backend')
                info[name]=binary(path)
            specs=Path(os.fsdecode(query('-print-file-name=specs')))
            info['external_specs']=binary(specs) if specs.is_absolute() else None
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            errors.append('unconfirmed_compiler_identity:'+type(exc).__name__)
        return {'identity':info,'errors':errors}


def add_provenance(manifest,directory):
    try:
        extra=proof.context(directory)
    except (ValueError,OSError,KeyError,TypeError,IndexError):
        extra={'schema':2,'errors':['incomplete_frontend_evidence']}
    if extra['errors']:
        # Distinct P0 and P1 refusal identities also invalidate the existing theory audit.
        extra['ineligible_role']=directory.name
    manifest['context']['frontend_dependencies_v2']=extra
    manifest['context_sha256']=digest(manifest['context'])
    manifest.pop('version_sha256',None)
    manifest['version_sha256']=digest(manifest)
    return manifest


def prepare(directory,tools,env,toolchain,fast,remaining=None):
    spool=directory/'compiler-spool'
    spool.mkdir(mode=0o700)
    bindir=tools/directory.name
    bindir.mkdir()
    wrapper=bindir/'gcc'
    shutil.copyfile(MODULE/('dispatch.sh' if fast else 'reference_gcc.py'),wrapper)
    wrapper.chmod(0o755)
    identity=toolchain.snapshot(env,remaining)
    save(directory/'compiler-identity.json',identity)
    return dict(PATH=str(bindir)+':'+env['PATH'],INCDEAGLE_FRONT_SPOOL=str(spool),INCDEAGLE_FRONT_MODULE=str(MODULE))


def confirm_identity(directory,env,toolchain,remaining=None):
    path=directory/'compiler-identity.json'
    original=read(path)
    if original!=toolchain.snapshot(env,remaining):
        original['errors'].append('compiler_changed_during_frontend')
        save(path,original)


class Candidate:
    def __init__(self,directory,tools,env,toolchain,remaining=None):
        self.directory=directory
        self.spool=directory/'compiler-spool'
        self.fast=hasattr(os,'pidfd_open')
        self.env=prepare(directory,tools,env,toolchain,self.fast,remaining)
        self.fd=None
        self.processed=set()
        self.reduce_ns=0
        if self.fast:
            os.mkfifo(self.spool/'requests',0o600)
            self.fd=os.open(self.spool/'requests',os.O_RDWR|os.O_NONBLOCK|os.O_CLOEXEC)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd=None

    def handle(self,slot):
        started=time.monotonic_ns()
        args=[os.fsdecode(x) for x in (slot/'argv').read_bytes().split(b'\0')[:-1]]
        kind=(slot/'kind').read_text().strip()
        try:
            if kind=='unknown':
                record={'kind':'unknown','argv':args,'errors':['unrecognized_gcc_invocation']}
            else:
                raw=(slot/'stdout').read_bytes()
                rc=int((slot/'status').read_text())
                if kind=='probe' and tuple(args) in proof.PROBES:
                    record=proof.probe_record(args,(slot/'stdin').read_bytes(),raw,rc)
                elif kind=='file' and proof.flags_supported(args):
                    cwd=Path(os.fsdecode((slot/'cwd').read_bytes().removesuffix(b'\n')))
                    legacy,record=proof.file_record(cwd,args,raw,rc,slot/'deps')
                    proof.emit(self.directory/'cpp.jsonl',legacy)
                else:
                    raise ValueError('unrecognized_gcc_invocation')
        except (ValueError,OSError,KeyError) as exc:
            record={'kind':'unknown','argv':args,'errors':['unconfirmed_dependency:'+type(exc).__name__]}
        proof.emit(self.directory/'frontend-calls.jsonl',record)
        self.processed.add(slot.name)
        self.reduce_ns+=time.monotonic_ns()-started

    def wait(self,proc,remaining):
        if not self.fast:
            return proc.wait(timeout=remaining())
        poll=select.poll()
        poll.register(self.fd,select.POLLIN)
        try:
            pidfd=os.pidfd_open(proc.pid)
        except OSError as exc:
            if exc.errno not in (errno.ENOSYS,errno.EPERM,errno.EINVAL,errno.ESRCH):
                raise
            pidfd=None
        if pidfd is not None:
            poll.register(pidfd,select.POLLIN)
        pending=b''
        try:
            while proc.poll() is None:
                timeout=max(1,math.ceil(remaining()*1000))
                events=poll.poll(timeout if pidfd is not None else min(timeout,5))
                if not any(fd==self.fd for fd,_ in events):
                    continue
                pending+=os.read(self.fd,65536)
                while b'\n' in pending:
                    line,pending=pending.split(b'\n',1)
                    if not line.isdigit() or len(line)>12:
                        raise ValueError('invalid local frontend notification')
                    slot=self.spool/('c.'+line.decode('ascii'))
                    self.handle(slot)
                    ack=os.open(slot/'ack',os.O_WRONLY|os.O_NONBLOCK|os.O_CLOEXEC)
                    try:os.write(ack,b'ok\n')
                    finally:os.close(ack)
            exit_observed=time.monotonic_ns()
            rc=proc.wait()
            reaped=time.monotonic_ns()
            # Probe stdout and stdin survive the compiler. Process them inside the measured frontend.
            for slot in sorted(self.spool.glob('c.*')):
                if slot.name not in self.processed:
                    if not (slot/'kind').exists():
                        proof.emit(self.directory/'frontend-calls.jsonl',dict(kind='unknown',errors=['incomplete_dispatch']))
                    else:
                        self.handle(slot)
            save(self.directory/'frontend-metrics.json',dict(pidfd=pidfd is not None,reducer_ns=self.reduce_ns,
                 exit_observed_ns=exit_observed,reaped_ns=reaped,calls=len(self.processed)))
            return rc
        finally:
            if pidfd is not None:os.close(pidfd)
