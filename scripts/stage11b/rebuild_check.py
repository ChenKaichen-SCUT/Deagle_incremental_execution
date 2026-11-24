"""Use a separately linked executable on both phases of an authenticated changed-graph capture."""
import hashlib,json,shutil,sys
from pathlib import Path
from negative import run_worker,stats
def check(run,build):
    d=run/'controls/independent-build';d.mkdir(parents=True,exist_ok=True)
    capture=run/'formal/lock12/1/GS';dirs=[]
    for side in ('old','new'):
        target=d/side;target.mkdir(exist_ok=True);(target/'worker').mkdir(exist_ok=True)
        for name in ('events.tsv','plan.txt','s8-input.bin','s8-graph.tsv'):shutil.copyfile(capture/side/name,target/name)
        dirs.append(target)
    rc,protocol=run_worker(build/'worker','GS',dirs,d)
    assert rc==0
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    results=[]
    for side,t in zip(('old','new'),dirs):
        ref=capture/side
        s=stats(t/'worker/stats.tsv');k=stats(t/'worker/closure-stats.tsv')
        assert sha(t/'answer.txt')==sha(ref/'answer.txt') and sha(t/'worker/search.bin')==sha(ref/'worker/search.bin')
        assert k['used_derived']==stats(ref/'worker/closure-stats.tsv')['used_derived']
        results.append(dict(side=side,sat_code=s['sat_code'],used_derived=k['used_derived'],originals=s['actually_reattached'],answer_sha256=sha(t/'answer.txt'),search_sha256=sha(t/'worker/search.bin')))
    (d/'rebuild.json').write_text(json.dumps(dict(binary=sha(build/'worker'),original_binary=sha(run/'build/worker'),protocol=protocol,results=results),indent=2)+'\n')
    shutil.copyfile(build/'build.sha256',d/'independent-build.sha256')
if __name__=='__main__':check(*map(Path,sys.argv[1:]))
