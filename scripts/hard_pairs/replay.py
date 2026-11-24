"""Independent Linux/WSL full verification from a frozen case, without any server files or network."""
import argparse
import json
from pathlib import Path
from run import queue,sha,write

def replay(case,out,binary,host):
    task=json.loads((case/'task.yaml').read_bytes())
    if sha(case/task['property'])!=task['property_sha256']:raise ValueError('property digest mismatch')
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    jobs=[]
    for side in ('old','new'):
        row=task['sides'][side]
        file=case/row['file']
        if sha(file)!=row['sha256']:raise ValueError('translation unit digest mismatch')
        name=file.name
        if name!=task['argv'][-1]:raise ValueError('incorrect translation unit')
        dest=out/'inputs'/side;dest.mkdir(parents=True,exist_ok=True)
        (dest/name).write_bytes(file.read_bytes())
        jobs.append(dict(out='local/'+side,sample=side,bound=int(task['argv'][task['argv'].index('--unwind')+1]),
                         phase='local',capture=True,argv=task['argv'],**task['limits'],
                         files={name:{'path':'inputs/'+side+'/'+name,'sha256':row['sha256']}}))
    plan=out/'independent.json';write(plan,jobs)
    queue(out,binary,plan,host,1)
    observed={k:json.loads((out/'local'/k/'receipt.json').read_bytes()) for k in task['sides']}
    print({k:v['result'] for k,v in observed.items()})
    if (case/'baseline.json').exists():
        baseline=json.loads((case/'baseline.json').read_bytes())['results']
        for k,v in observed.items():
            if any(v[key]!=baseline[k][key] for key in ('binary','argv','exit','result','properties')):
                raise RuntimeError('frozen property check differs on '+k)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('case','out','binary'):p.add_argument(key,type=Path)
    p.add_argument('--host',default='wsl-local')
    a=p.parse_args();replay(a.case,a.out,a.binary,a.host)
