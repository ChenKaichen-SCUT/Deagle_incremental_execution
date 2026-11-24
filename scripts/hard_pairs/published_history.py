"""Inspect upstream source history of promising passing versions; exclude metadata-only changes."""
import concurrent.futures
import json
import urllib.parse
from history25 import API,get
from prepare import E,TAG,dump
PATHS=['c/weaver/parallel-ticket-7.wvr.c','c/pthread/fib_safe.h','c/pthread-deagle/circular_buffer_ok.c',
       'c/pthread-ext/25_stack_longest-1.c','c/weaver/popl20-more-buffer-series2.wvr.c']
def hist(path):
    url=API+'commits?'+urllib.parse.urlencode({'ref_name':TAG,'path':path,'per_page':5})
    mirror='https://api.github.com/repos/sosy-lab/sv-benchmarks/commits?'+urllib.parse.urlencode({'sha':TAG,'path':path,'per_page':15})
    try:
        rows=json.loads(get(mirror))
        return path,[{'id':r['sha'],'title':r['commit']['message'].splitlines()[0],'parent_ids':[v['sha'] for v in r['parents']]} for r in rows]
    except OSError:
        try:
            rows=json.loads(get(url,100));return path,[{'id':r['id'],'title':r['title'],'parent_ids':r['parent_ids']} for r in rows]
        except OSError as exc:
            return path,[{'id':'UNRESOLVED','title':str(exc),'parent_ids':[]}]
if __name__=='__main__':
    import sys
    target=E/'svcomp25/public-family-history.json'
    out=json.loads(target.read_bytes()) if target.is_file() else {}
    paths=sys.argv[1:] or PATHS
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as p:out.update(p.map(hist,paths))
    dump(target,out)
    for name,rows in out.items(): print(name,[(r['id'][:8],r['title']) for r in rows])
