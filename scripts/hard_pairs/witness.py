"""Compare the original failure projection across exploratory and isolated native runs."""
import json
from pathlib import Path
from prepare import ROOT,E,dump,h
def witness(job,fields):
    d=ROOT.parent/'returned'/job;r=json.loads((d/'receipt.json').read_bytes());p=d/r['attempt']/'result.json'
    target=next(v for m in json.loads(p.read_bytes()) for v in m.get('result',[]) if v['property']=='reach_error.assertion.1')
    assert target['status']=='FAILURE' and target['trace'][-1]['stepType']=='failure'
    out=[]
    for t in target['trace']:
        fn=t.get('sourceLocation',{}).get('function');lhs=t.get('lhs')
        if (fn,lhs) in fields or t['stepType']=='failure':
            out.append([t.get('thread'),fn,lhs,t.get('value',{}).get('data'),t['stepType']])
    return dict(job=job,receipt=r['identity'],raw_sha256=h(p.read_bytes()),trace_steps=len(target['trace']),projection=out)
def main():
    out={}
    table=[('circular-buffer','buffer-b8','extended',{('t1','i'),('t2','i'),('t2','return_value_removeLogElement'),('insertLogElement','next'),('removeLogElement','first')}),
           ('ldv-publication','ldv-join-b4','candidates',{('module_init','pdev'),('thread1','pdev'),('ldv_assert','expression')})]
    for case,key,pilot,fields in table:
        a,b=[witness(phase+'/'+key,fields) for phase in (pilot,'formal')]
        assert a['projection']==b['projection'] and len(a['projection'])>=3
        out[case]=[a,b]
    dump(E/'manual-witnesses.json',out)
if __name__=='__main__':main()
