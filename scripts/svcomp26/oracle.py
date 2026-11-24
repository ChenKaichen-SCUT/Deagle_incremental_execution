"""Independent Closure run on precisely the YAML translation unit, with structured property and unwind checking."""
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
import yaml
from config import DEAGLE,ROOT,TASKS,folder

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_bytes((json.dumps(obj,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode())
def read(p):return json.loads(p.read_bytes())
def metadata(task):
    directory=folder(task);spec=yaml.safe_load((directory/(task+'.yml')).read_bytes())
    prop=next((p for p in spec['properties'] if p['property_file'].endswith('/unreach-call.prp')),None)
    if not prop:return None
    prp=(directory/prop['property_file']).resolve()
    if prp.read_text().strip()!='CHECK( init(main()), LTL(G ! call(reach_error())) )':raise ValueError('unknown reachability specification')
    opts=spec['options']; assert opts['language']=='C' and opts['data_model'] in ('ILP32','LP64')
    return dict(data_model=opts['data_model'],bits={'ILP32':32,'LP64':64}[opts['data_model']],bound=TASKS[task][1],
                input=spec['input_files'],property_sha256=sha(prp),yaml_sha256=sha(directory/(task+'.yml')),expected=prop['expected_verdict'])
def options(meta):
    return ['--function','main','--deagle-closure','--mm','sc','--'+str(meta['bits']),'--unwind',str(meta['bound']),'--unwinding-assertions']
def interpret(result,rc):
    groups=[m['result'] for m in result if 'result' in m];totals=[m['cProverStatus'] for m in result if 'cProverStatus' in m]
    if len(groups)!=1 or len(totals)!=1 or (rc,totals[0]) not in ((10,'failure'),(0,'success'),(5,'inconclusive')):
        raise ValueError('incomplete result or exit mismatch')
    rows=groups[0];targets=[r for r in rows if r['property'].startswith('reach_error.assertion.') and r.get('sourceLocation',{}).get('function')=='reach_error']
    levels={r['property']:r['status'] for r in rows};uw={k:v for k,v in levels.items() if 'unwind' in k}
    cs='UNRESOLVED_PROPERTY'
    witness=None
    if len(targets)==1:
        t=targets[0];status=t['status']
        if status=='FAILURE':
            trace=t.get('trace',[])
            failures=[s for s in trace if s.get('stepType')=='failure' and s.get('property')==t['property']]
            if failures and all(f.get('sourceLocation',{}).get('function')=='reach_error' for f in failures):
                cs='VIOLATION';witness=t
            else:cs='MISSING_COUNTEREXAMPLE'
        elif any(v!='SUCCESS' for v in uw.values()):cs='INCOMPLETE_UNWINDING'
        elif rc==0 and status=='SUCCESS' and set(levels.values())=={'SUCCESS'}:cs='BOUNDED_PASS'
        else:cs='INCONCLUSIVE'
    return dict(classification=cs,target=targets[0]['property'] if len(targets)==1 else None,
                property_rows=levels,unwinding=uw,overall=totals[0]),witness
def run(task,exe,out,source=None,timeout=120,target_only=False):
    out.mkdir(exist_ok=False,parents=True)
    meta=metadata(task)
    if not meta:
        save(out/'receipt.json',dict(task=task,classification='YAML_OTHER_PROPERTY'));return
    p=source or folder(task)/meta['input']
    # Identical original .i bytes, data model and neutral filename in all independent runs.
    (out/'program.i').write_bytes(p.read_bytes())
    cmd=[str(exe),*options(meta),*(['--property','reach_error.assertion.1'] if target_only else []),'--trace','--json-ui','program.i']
    env={k:os.environ[k] for k in ('PATH','LANG') if k in os.environ}
    env.update(LC_ALL='C',INCDEAGLE_JSON_OUTPUT=str(out/'result.json'))
    t=time.monotonic_ns()
    with (out/'stdout').open('wb') as stdout,(out/'stderr').open('wb') as stderr:
        proc=subprocess.Popen(cmd,cwd=out,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        try:rc=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);proc.wait();rc=124
    elapsed=time.monotonic_ns()-t
    doc=dict(task=task,input_sha256=sha(out/'program.i'),native_sha256=sha(exe),argv=cmd,meta=meta,exit=rc,elapsed_ns=elapsed,timeout_seconds=timeout)
    body=(out/'stdout').read_text(errors='replace')+'\n'+(out/'stderr').read_text(errors='replace')
    try:
        v,witness=interpret(read(out/'result.json'),rc);doc.update(v)
        if witness:save(out/'target-trace.json',witness)
    except (ValueError,KeyError,OSError,TypeError) as e:
        doc.update(classification='TIMEOUT' if rc==124 else 'TOOL_FAILURE',detail=str(e))
    messages=re.findall(r'(?im)^.*(?:no body for|unsupported|not supported|ignoring.*(?:pthread|atomic)|warning:.*(?:pthread|atomic)).*$',body)
    if (out/'result.json').exists():
        try:
            msgs=[m.get('messageText','') for m in read(out/'result.json') if isinstance(m,dict)]
            messages.extend(x for x in msgs if re.search(r'no body for|unsupported|not supported|ignor.*(?:pthread|atomic)',x,re.I))
        except (TypeError,ValueError):pass
    doc['model_warnings']=sorted(set(x[:500] for x in messages))
    try:
        doc['native_diagnostics']=[dict(level=m['messageType'],message=m.get('messageText','')) for m in read(out/'result.json') if m.get('messageType') in ('WARNING','ERROR')]
    except (OSError,ValueError):doc['native_diagnostics']=[]
    if any(re.search(r'(?:no body for|unsupported|not supported|ignor).*?(?:pthread_|__atomic_|__VERIFIER_atomic)',s,re.I) for s in messages):
        doc['provisional']=doc['classification'];doc['classification']='UNSUPPORTED_PRIMITIVE'
    save(out/'receipt.json',doc)
    print(task,doc['classification'],rc,round(elapsed/1e9,3),doc.get('target'),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('exe',type=Path);p.add_argument('out',type=Path);p.add_argument('tasks',nargs='*')
    p.add_argument('--target-only',action='store_true');a=p.parse_args();assert sha(a.exe)==DEAGLE
    for task in a.tasks or TASKS:run(task,a.exe.resolve(),a.out.resolve()/task,target_only=a.target_only)
