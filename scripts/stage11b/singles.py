"""Independently run only the prespecified subjects. Keep incomplete/error rows."""
import argparse,hashlib,json,os,resource,signal,subprocess,tarfile,time
from pathlib import Path
def sha(b):return hashlib.sha256(b).hexdigest()
def record(file,x):file.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n')
def limit():
    resource.setrlimit(resource.RLIMIT_AS,(4<<30,4<<30))
def execute(d,exe,unit,argc,timeout,instrument=None):
    import gzip
    output=d/'output.json'
    argv=[str(exe),*argc,'--trace','--json-ui',unit]
    env={'PATH':os.environ['PATH'],'LC_ALL':'C','INCDEAGLE_JSON_OUTPUT':str(output)}
    if instrument:env.update(instrument)
    start=time.monotonic_ns()
    with (d/'stdout').open('wb') as out,(d/'stderr').open('wb') as err:
        proc=subprocess.Popen(argv,cwd=d,env=env,stdout=out,stderr=err,start_new_session=True,preexec_fn=limit)
        late=False
        try:rc=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL);rc=proc.wait();late=True
    spent=time.monotonic_ns()-start
    raw=output.read_bytes() if output.exists() else b''
    try:values=json.loads(raw)
    except ValueError:values=[]
    properties=[(p['property'],p['status']) for row in values for p in row.get('result',[])]
    status='TIME_LIMIT' if late else 'UNINTERPRETABLE'
    if not late and rc in (0,10) and properties:
        status='INCOMPLETE_UNWINDING' if any('unwind' in k and v!='SUCCESS' for k,v in properties) else (
            'ASSERTION_VIOLATION' if any(s=='FAILURE' for _,s in properties) else 'BOUNDED_PASS' if all(s=='SUCCESS' for _,s in properties) else 'UNKNOWN')
    evidence={'wall_ns':spent,'code':rc,'classification':status,'properties':properties,'argv':argv[1:],
        'max_address_space':4<<30,'timeout_s':timeout,'output_sha256':sha(raw),'strict_sc':'UNASSESSED'}
    for n in ('stdout','stderr','output.json'):
        p=d/n
        if not p.exists():continue
        blob=p.read_bytes();(d/(n+'.gz')).write_bytes(gzip.compress(blob,mtime=0))
    return evidence
def main(exe,out,panel):
    m=json.loads((panel/'selection.json').read_bytes());out.mkdir(exist_ok=True,parents=True)
    with tarfile.open(panel/'inputs.tar.gz') as archive:
        # Weak controls first. Tail latencies and unknown results remain in the panel.
        for row in sorted(m['rows'],key=lambda r:(r['kind']!='weak-control',r['task'])):
            d=out/row['task'];d.mkdir(exist_ok=True)
            if (d/'receipt.json').exists():continue
            unit=row['unit'];raw=archive.extractfile(row['task']+'/'+unit).read()
            assert sha(raw)==row['source_sha256'];(d/unit).write_bytes(raw)
            res={'task':row['task'],'source_sha256':sha(raw),'artifact_kind':row['kind'],'data_model':row['data_model']}
            if not row['reach']:
                # Paper runner ignores the property list; a reachability run cannot check this YAML obligation.
                res['classification']='EXCLUDED_YAML_NO_UNREACH_CALL'
            else:
                assert row['data_model']=='ILP32'
                bound=5 if row['kind']=='incomplete-control' else 2
                res.update(execute(d,exe,unit,['--function','main','--deagle-closure','--mm','sc','--32','--unwind',str(bound),'--unwinding-assertions'],60))
                if row['kind']=='weak-control':
                    res['strict_sc']='QUARANTINE_NATIVE; SEE independent full write orders'
            record(d/'receipt.json',res);print(row['task'],res['classification'],flush=True)
if __name__=='__main__':
    import sys
    main(*[Path(a).resolve() for a in sys.argv[1:]])
