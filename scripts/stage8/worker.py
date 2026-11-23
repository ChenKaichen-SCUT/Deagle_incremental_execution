"""Run one matched old/candidate verification in a memory-limited service."""
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle import repair
from incdeagle.adapters.deagle import classify
from incdeagle.model import compare as model_compare
from incdeagle.model.identity import file_sha,read,save
from incdeagle.theory import cache,context
from scripts.stage2.check_case import load_case
from scripts.stage4 import change_provider,session as native
from scripts.stage5.session import TheorySession
from scripts.stage7 import worker as previous
from scripts.stage8.controller_meter import Recorder
base_mark=previous.mark

def mark():
    result=base_mark()
    group=previous.group()
    result["io_stat"]=(group/"io.stat").read_text()
    result["current_bytes"]=int((group/"memory.current").read_text())
    return result

def memory(pid):
    try:
        pairs=[s.split(':',1) for s in Path('/proc',str(pid),'smaps_rollup').read_text().splitlines()[1:] if ':' in s]
        values={k:int(v.split()[0]) for k,v in pairs if k in ('Pss','Rss','Private_Dirty','Private_Clean')}
        return {"pid":pid,**values}
    except (FileNotFoundError,PermissionError):
        return None

def perform(case,folder,settings):
    mode=settings["mode"]
    detail=settings["detail"]
    lock=read(Path(settings["lock"]))
    _,gamma,phi=load_case(case)
    assert int((previous.group()/"memory.max").read_text())==gamma["limits"]["memory_bytes"]
    assert set(os.sched_getaffinity(0))==set(settings["affinity"])
    events=[]
    times={}
    meter=Recorder()
    checkpoint={}
    resource_before=resource.getrusage(resource.RUSAGE_CHILDREN)
    class Process(subprocess.Popen):
        def __init__(self, argv, *args, **kwargs):
            env=kwargs.get('env')
            self.s8role=None
            if env is not None and any(str(a).endswith('/deagle_exe') for a in argv):
                d=Path(env['INCDEAGLE_JSON_OUTPUT']).parent
                self.s8role=d.name
                env=dict(env,S8_MODE=mode)
                if detail:
                    env.update(S8_OUT=str(d),S8_PREFIX=str(settings["prefix"]),
                               S8_RF=settings["rf"],S8_PO=settings["po"],
                               S8_GCC_ORIGINAL=str(ROOT/'scripts/stage3/record_gcc.py'))
                    if settings.get('stream'):env['S8_STREAM']='1'
                kwargs['env']=env
                begin=time.monotonic_ns()
            super().__init__(argv,*args,**kwargs)
            if self.s8role:
                events.append({"kind":"launch","role":self.s8role,"pid":self.pid,"begin":begin,"end":time.monotonic_ns()})
        def wait(self,*args,**kwargs):
            start=time.monotonic_ns()
            result=super().wait(*args,**kwargs)
            if self.s8role:
                events.append({"kind":"wait","role":self.s8role,"pid":self.pid,"begin":start,"end":time.monotonic_ns(),"rc":result})
            return result
    class Theory(TheorySession):
        binary=Path(lock["development_binary"])
        release_lock=Path(settings["lock"])
        def prepare(self,directory,tool):
            env=super().prepare(directory,tool)
            if detail:env["INCDEAGLE_S5_HELPER"]=str(ROOT/'scripts/stage8/theory_probe.py')
            return env
    real_context=native.candidate_context
    def select(*args):
        versions,changes=real_context(*args)
        if mode=="F2" and not changes["preflight_refusal"]:
            changes={**changes,"preflight_refusal":"stage8_forced_full_after_checks"}
        return versions,changes
    orig_copy=shutil.copyfile
    def copy(src,dst,*args,**kwargs):
        if detail and Path(src)==ROOT/'scripts/stage3/record_gcc.py' and Path(dst).name=='gcc':
            src=ROOT/'scripts/stage8/gcc_probe.py'
        return orig_copy(src,dst,*args,**kwargs)
    class Replay(previous.FrozenReplay):
        def produce(self,old,verdict,target,ready,process,warmup_wall):
            if ready:
                checkpoint.update(moment="after_P0_before_submission",memory=memory(ready["checkpoint_pid"]))
            return super().produce(old,verdict,target,ready,process,warmup_wall)
    orig_mark=mark
    def tracked_mark():
        sample=orig_mark()
        if "old_instrumented_start" in times and "incremental_start" not in times:
            meter.phase="candidate"
        return sample
    def plain(version):
        role='old_full' if version=='old' else 'full'
        dest=folder/role
        dest.mkdir()
        measure=times
        meter.phase=version
        measure[role+'_start']=mark()
        prog='old/program.c' if version=='old' else 'candidate/program.c'
        for name,local in [(prog,'program.c'),('harness.c','harness.c')]:
            shutil.copyfile(case/name,dest/local)
            assert file_sha(case/name)==file_sha(dest/local)
        if mode=='F0' and not detail:
            binary=ROOT/'third_party/deagle-baseline/src/cbmc/deagle_exe'
            expected=gamma['binary_sha256']
        else:
            btype='baseline' if mode=='F0' else 'development'
            binary=Path(lock[btype+'_binary'])
            expected=lock[btype+'_sha256']
        assert file_sha(binary)==expected
        cmd=['/usr/bin/timeout','--kill-after=5',str(gamma['limits']['timeout_seconds']),str(binary),*gamma['source_argv'],*gamma['verification_output'],'harness.c']
        env=dict(os.environ,LC_ALL="C",INCDEAGLE_JSON_OUTPUT=str(dest/'result.json'))
        if settings.get('observe') and mode=='F1':env['INCDEAGLE_OBSERVE_DIR']=str(dest)
        with (dest/'diagnostic.stdout').open('wb') as out,(dest/'diagnostic.stderr').open('wb') as err:
            with meter.span('native_subprocess'):
                rc=subprocess.run(cmd,cwd=dest,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err).returncode
        verdict,target=classify((dest/'result.json').read_bytes(),rc,phi)
        assert verdict['classification'] in ('VIOLATION','NO_VIOLATION_WITHIN_BOUND') and rc in (0,10),(rc,verdict)
        console=(dest/'diagnostic.stdout').read_bytes()
        assert b"Use Deagle's closure solver" in console and b"Set Deagle closure solver's graph" in console
        hashes={'program.c':file_sha(case/prog),'harness.c':file_sha(case/'harness.c')}
        trace=previous.normalized(dest,target if verdict['classification']=='VIOLATION' else None,phi,gamma,hashes,version)
        save(dest/'verdict.json',verdict)
        measure[role+'_end']=mark()
        return verdict,trace,expected
    with ExitStack() as stack:
        stack.enter_context(patch.object(subprocess,'Popen',Process))
        stack.enter_context(patch.object(native,'candidate_context',select))
        stack.enter_context(patch.object(previous,'FrozenReplay',Replay))
        stack.enter_context(patch.object(previous,'TheorySession',Theory))
        stack.enter_context(patch.object(shutil,'copyfile',copy))
        stack.enter_context(patch.object(previous,'mark',tracked_mark))
        if detail:
            for obj,names in [(native,['candidate_context','manifest','save','read','file_sha']),(shutil,['copyfile']),
                    (change_provider,['changes','compare_mapping','read']),(model_compare,['file_sha','read']),
                    (previous,['file_sha','normalized','summarize_theory']),(repair,['file_sha','original_hashes']),
                    (cache,['read','save','digest','derive','check','freeze','collect']),
                    (context,['read','digest'])]:
                for name in names:
                    if hasattr(obj,name):meter.hook(stack,obj,name,name)
        if mode in ('F0','F1'):
            old,old_trace,old_binary=plain('old')
            new,trace,binary=plain('candidate')
            data={"old_verdict":old,"verdict":new,"old_trace":old_trace,"trace":trace,"binary_sha256":binary,"path":"full"}
        else:
            data=previous.incremental(case,folder,times)
    assert data['old_verdict']['classification']=='VIOLATION'
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    return {**data,"times":times,"processes":events,"checkpoint":checkpoint,"python_spans":dict(meter.totals),
        "child_cpu_user":usage.ru_utime-resource_before.ru_utime,"child_cpu_system":usage.ru_stime-resource_before.ru_stime,
        "child_maxrss_kib":usage.ru_maxrss,"controller_maxrss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


if __name__=='__main__':
    case,folder=map(Path,sys.argv[1:])
    save(folder/'group.json',{'path':str(previous.group()),'pid':os.getpid()})
    opts=read(folder/'settings.json')
    result=perform(case,folder,opts)
    save(folder/'measurement.json',result)
