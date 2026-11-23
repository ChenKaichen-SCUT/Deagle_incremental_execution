"""Run isolated dependency/invalid-input changes through real Deagle sessions and independent candidates."""
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import file_sha,read,save
from scripts.stage4 import session as native
from scripts.stage5.session import TheorySession,summarize_theory
from scripts.stage9 import frontend

CASES=('header','macro_flag','compiler_config','abi','alias','nested','unknown_dependency','missing_attachment','damaged_stream')


def test(case_id,source,out):
    d=out/case_id;d.mkdir()
    case=d/'input/batch_total'
    shutil.copytree(source,case)
    headers=d/'headers';headers.mkdir()
    entry=headers/'entry.h'
    entry.write_text('#define S9_BASE 1\n')
    (headers/'alias.h').symlink_to('entry.h')
    (headers/'left.h').write_text('#define S9_BRANCH 1\n')
    (headers/'right.h').write_text('#define S9_BRANCH 2\n')
    if case_id=='nested':
        entry.write_text('#define USE_RIGHT 0\n#if USE_RIGHT\n#include "right.h"\n#else\n#include "left.h"\n#endif\n')
    if case_id=='abi':entry.write_text('struct s9_item { char field; };\n')
    for version in ('old','candidate'):
        path=case/version/'program.c'
        include='alias.h' if case_id=='alias' and version=='candidate' else 'entry.h'
        program=path.read_text()
        if case_id=='abi':
            program='volatile struct s9_item s9_value;\n'+program.replace('shipped_units +=','s9_value.field = boxes;\n    shipped_units +=')
        program='#include "'+include+'"\n'+program
        if case_id=='unknown_dependency' and version=='candidate':
            program+='\n#line 310 "absent-evidence-header.h"\nstatic int stage9_unresolved;\n'
        path.write_text(program)
    alternate=d/'alternate-compiler';alternate.mkdir()
    for name in ('cc1','cc1plus'):
        real=subprocess.check_output(['/usr/bin/gcc','-print-prog-name='+name],text=True).strip()
        f=alternate/name;f.write_text('#!/bin/sh\nexec '+real+' "$@"\n');f.chmod(0o755)
    class Old(TheorySession):
        def capture(self,directory,manifest):
            result=super().capture(directory,manifest)
            if case_id=='header':entry.write_text('#define S9_BASE 2\n')
            if case_id=='nested':entry.write_text(entry.read_text().replace('USE_RIGHT 0','USE_RIGHT 1'))
            if case_id=='abi':entry.write_text('struct s9_item { long field; };\n')
            return result
    real_proc=subprocess.Popen
    def launch(argv,*args,**kwargs):
        env=kwargs.get('env',{})
        if 'INCDEAGLE_JSON_OUTPUT' in env and Path(env['INCDEAGLE_JSON_OUTPUT']).parent.name in ('frontend','candidate'):
            if case_id=='macro_flag':argv=[*argv[:-1],'-DS9_OPTION=17',argv[-1]]
            if case_id=='compiler_config':kwargs['env']={**env,'COMPILER_PATH':str(alternate)}
        return real_proc(argv,*args,**kwargs)
    class Candidate(frontend.Candidate):
        def __init__(self,directory,tools,env,toolchain,remaining=None):
            extra={'COMPILER_PATH':str(alternate)} if case_id=='compiler_config' else {}
            super().__init__(directory,tools,{**env,**extra},toolchain,remaining)
            self.env.update(extra)
    original_context=native.candidate_context
    def admission(old,front,*args):
        if case_id=='missing_attachment':
            (front/'frontend-calls.jsonl').rename(front/'frontend-calls-held.jsonl')
        if case_id=='damaged_stream':
            stream=next((front/'compiler-spool').glob('*/stdout'))
            with stream.open('ab') as f:f.write(b'changed after recording\n')
        return original_context(old,front,*args)
    with patch.dict(os.environ,{'CPATH':str(headers)}),patch.object(subprocess,'Popen',launch), \
         patch.object(frontend,'Candidate',Candidate),patch.object(native,'candidate_context',admission):
        session=native.run_pair(case,d/'pair',theory=Old())
    independent=d/'independent';independent.mkdir()
    for src,dst in [('candidate/program.c','program.c'),('harness.c','harness.c')]:
        shutil.copyfile(case/src,independent/dst)
    gamma=read(case/'gamma.json');phi=read(case/'phi.json')
    env=dict(os.environ,CPATH=str(headers),LC_ALL='C',INCDEAGLE_JSON_OUTPUT=str(independent/'result.json'))
    if case_id=='compiler_config':env['COMPILER_PATH']=str(alternate)
    cmd=[str(TheorySession.binary),*gamma['source_argv'],*gamma['verification_output']]
    if case_id=='macro_flag':cmd.append('-DS9_OPTION=17')
    cmd.append('harness.c')
    with (independent/'stdout').open('wb') as so,(independent/'stderr').open('wb') as se:
        p=subprocess.run(cmd,cwd=independent,env=env,stdout=so,stderr=se,timeout=300)
    full,_=classify((independent/'result.json').read_bytes(),p.returncode,phi)
    assert full==session['candidate'] and full['classification']=='NO_VIOLATION_WITHIN_BOUND',case_id
    pair=d/'pair'
    theory=summarize_theory(pair)
    manifests=[read(pair/n/'manifest.json') for n in ('old','frontend')]
    a,b=[m['context']['frontend_dependencies_v2'] for m in manifests]
    diff=read(pair/'source-changes.json')
    if case_id=='alias':
        assert a['headers']==b['headers'] and a['units']==b['units']
    else:
        assert session['path']=='full_fallback' and session['native']['reused_prefix_symex_steps']==0
        assert theory['imported']==0 and read(pair/'candidate/native-import.json')['rows']==[]
    if case_id in ('header','abi'):assert a['headers'][str(entry)]!=b['headers'][str(entry)]
    if case_id=='macro_flag':assert manifests[0]['context']['cpp_flags']!=manifests[1]['context']['cpp_flags']
    if case_id=='compiler_config':
        assert a['compiler']['cc1']!=b['compiler']['cc1'] and b['errors']
    if case_id=='nested':
        assert str(headers/'left.h') in a['headers'] and str(headers/'right.h') in b['headers']
    if case_id=='unknown_dependency':assert 'unconfirmed_line_marker' in b['errors']
    if case_id=='missing_attachment':assert 'incomplete_frontend_evidence' in b['errors']
    if case_id=='damaged_stream':assert 'incomplete_or_modified_preprocessor_stream' in b['errors']
    item=dict(test=case_id,path=session['path'],reason=session['fallback_reason'],frontend_errors=b['errors'],
              configuration_changes=diff.get('configuration_changes'),p0=session['old']['classification'],
              p1=full['classification'],independent_exit=p.returncode,imported=theory['imported'],
              skipped=session['native']['reused_prefix_symex_steps'],evidence=[m['context_sha256'] for m in manifests])
    save(d/'receipt.json',item);print(case_id,item['path'],item['reason'],flush=True)
    return item


def invalid(source,out):
    original=(source/'old/program.c').read_text()
    for name,replacement in [('syntax','boxes * ;'),('gcc_error','boxes * 2;\n#error intended-stage9-error')]:
        if (out/name/'receipt.json').exists():continue
        d=out/name;d.mkdir()
        bad=original.replace('boxes * 2;',replacement)
        patchfile=d/'bad.diff'
        patchfile.write_text(''.join(difflib.unified_diff(original.splitlines(True),bad.splitlines(True),
                             fromfile='a/program.c',tofile='b/program.c')))
        cmd=[sys.executable,'-B','-m','incdeagle.cli','run-case','--case',str(source/'task.yaml'),
             '--out',str(d/'run'),'--repair','manual','--patch',str(patchfile)]
        with (d/'stdout').open('wb') as so,(d/'stderr').open('wb') as se:
            p=subprocess.run(cmd,cwd=ROOT,stdout=so,stderr=se,timeout=90)
        state=read(d/'run/workflow.json')
        assert p.returncode==2 and not state['baseline_started'] and state['status'] in ('ERROR','INVALID_PATCH')
        assert not (d/'run/frozen.json').exists()
        front=next((d/'run').rglob('frontend/frontend-calls.jsonl')).parent
        rows=[json.loads(r) for r in (front/'frontend-calls.jsonl').read_bytes().splitlines()]
        if name=='gcc_error':assert any(r.get('returncode',0)!=0 for r in rows)
        if name=='syntax':assert state['status']=='INVALID_PATCH'
        save(d/'receipt.json',dict(test=name,status=state['status'],reason=state['online_reason'],
             baseline_started=False,cli_rc=p.returncode,gcc_exits=[r.get('returncode') for r in rows]))
        print(name,state['status'],flush=True)


def resource(out):
    d=out/'resources';d.mkdir()
    front=d/'frontend';front.mkdir()
    tools=d/'tools';tools.mkdir()
    guard=frontend.Candidate(front,tools,dict(os.environ),frontend.Toolchain())
    # A real process group that fails to exit by the budget. Exercise the production wait/cleanup path.
    pidfile=d/'sleeper'
    proc=subprocess.Popen(['/bin/sh','-c','sleep 20 & echo $! > "$1"; wait','sh',str(pidfile)],
                          start_new_session=True,stdin=subprocess.PIPE)
    deadline=time.monotonic()+0.15
    def left():
        t=deadline-time.monotonic()
        if t<=0:raise TimeoutError('candidate budget')
        return t
    try:
        guard.wait(proc,left)
        raise AssertionError('expected timeout')
    except TimeoutError:pass
    finally:native.clean_process(proc);guard.close()
    child=Path('/proc')/pidfile.read_text().strip()/'stat'
    assert proc.poll() is not None and (not child.exists() or child.read_text().split()[2]=='Z')
    bad=subprocess.run(['systemd-run','--quiet','--pipe','--wait','--collect','-p','MemoryMax=67108864',
       sys.executable,'-B',str(ROOT/'scripts/stage5/session.py'),'batch_total','--contained','--out',str(d/'wrong-budget')],
       capture_output=True)
    assert bad.returncode!=0 and b'Wrong cgroup limit' in bad.stderr+bad.stdout
    (d/'wrong-budget.stderr').write_bytes(bad.stderr+bad.stdout)
    # The orchestrator reads the kernel's actual OOM kill counter in an isolated small cgroup.
    from incdeagle.comparison import bounded
    limited=d/'oom';limited.mkdir()
    result=bounded([sys.executable,'-c','x=bytearray(268435456)'],limited,limited,
                   {'timeout_seconds':10,'memory_bytes':64*1024**2},env={})
    save(limited/'service.json',result)
    assert result['resource_status']=='OOM',result
    save(d/'receipt.json',dict(timeout=True,leader_exit=proc.returncode,child_live=False,
        refused_wrong_memory_limit=True,oom=result['resource_status']))
    print('deadline, cleanup, cgroup-limit refusal and OOM',flush=True)


def main(archive,out):
    out.mkdir(parents=True,exist_ok=True)
    source=archive/read(ROOT/'reports/evidence/stage-07/matrix.json')['batch_total']['case_dir']
    for item in (*CASES,'syntax','gcc_error','resources'):
        trial=out/item
        if trial.exists() and not (trial/'receipt.json').exists():
            archive_dir=out/'incomplete-attempts'
            archive_dir.mkdir(exist_ok=True)
            trial.rename(archive_dir/(item+'-'+str(time.monotonic_ns())))
    for name in CASES:
        if not (out/name/'receipt.json').exists():test(name,source,out)
    invalid(source,out)
    if not (out/'resources/receipt.json').exists():resource(out)

if __name__=='__main__':main(*[Path(s).resolve() for s in sys.argv[1:]])
