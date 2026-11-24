"""Resolve the public 2025 tag and inspect just the overlapping selected source families."""
import concurrent.futures
import json
import urllib.parse
import urllib.request
from prepare import E, h, dump

API='https://gitlab.com/api/v4/projects/sosy-lab%2Fbenchmarking%2Fsv-benchmarks/repository/'
COMMIT='1e5856db49f3a4766f416cc60382aa92012b2939'
def get(url,timeout=20):
    req=urllib.request.Request(url,headers={'User-Agent':'Deagle benchmark provenance'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=timeout) as response:
        return response.read()
def main():
    out=E/'svcomp25';out.mkdir(exist_ok=True,parents=True)
    tag=out/'tag.json'
    if not tag.exists():tag.write_bytes(get(API+'tags/svcomp25'))
    assert json.loads(tag.read_bytes())['commit']['id']==COMMIT
    rows=json.loads((E/'inventory.json').read_bytes())
    keys=['buffer','rw0','unwind0','25_stack_longer-1','25_stack_longest-2','26_stack_cas_longer-1','fib-safe10','buffer-series1','ticket7']
    def inspect(key):
        r=rows[key];ret={'task':r['task'],'tag_commit':COMMIT}
        for kind,name,sha in [('yaml',r['task'],r['yaml_sha256']),('source',str(Path(r['task']).parent.as_posix()+'/'+r['original']),r['public_sha256'])]:
            loc='c/'+name;url=API+'files/'+urllib.parse.quote(loc,safe='')+'/raw?ref='+COMMIT
            try:data=get(url)
            except OSError:
                url='https://raw.githubusercontent.com/sosy-lab/sv-benchmarks/'+COMMIT+'/'+loc
                data=get(url)
            ret[kind]=dict(path=loc,url=url,sha256=h(data),bytes=len(data),matches_current=h(data)==sha)
            if h(data)!=sha:(out/(key+'-'+kind)).write_bytes(data)
        return key,ret
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:hist=dict(pool.map(inspect,keys))
    dump(out/'overlap.json',hist)
if __name__=='__main__':main()
