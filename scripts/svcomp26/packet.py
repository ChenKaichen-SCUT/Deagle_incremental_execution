import re
import sys
from config import ROOT
from oracle import read,sha
sys.path.insert(0,str(ROOT))
from incdeagle.repair_input import public_text,wire_text

CONTRACT={
 'read_write_lock-2':'Maintain shared read/write exclusion, allow concurrent readers, preserve x=3, the independent reads/comparison, and exact reader reference counting including release.',
 'arithmetic_prog_bad':'Preserve the producer and consumer handoff, the number of processed items and the completion flag. total accumulates the zero-based index of each consumed item exactly once; there is no fourth consumed item.',
 'stack-2':'Preserve LIFO and nondeterministic payloads, normal push/pop, capacity and explicit overflow/underflow results. Consumers may only consume available items.',
 'unwind1-1':'The writer publishes a nonnegative loop-work limit up to the configured N. Preserve nondeterministic choice, the values of already-valid requests, both threads, the reader loop and its check. The implementation must also work for other nonnegative configured bounds.',
}
STACK='An initially empty stack must become nonempty after a successful push. Preserve top, the linked payload, allocation failure and the meaning of isEmpty. Keep calling the original check after successful push.'
START={'read_write_lock-2':r'^int w\s*=', 'arithmetic_prog_bad':r'^int num\s*;', 'stack-2':r'^static int top\s*=', 'unwind1-1':r'^int _N\s*;'}
def region(task,text):
    a=re.search(START.get(task,r'^int memory\['),text,re.M)
    b=re.search(r'^int main\s*\(',text,re.M)
    if not a or not b or b.start()<a.start():raise ValueError('unsupported source boundary')
    return a.start(),b.start()
def packet_for(task,src,oracle):
    doc=read(oracle/'receipt.json')
    assert doc['classification']=='VIOLATION' and doc['input_sha256']==sha(src)
    target=read(oracle/'target-trace.json');trace=target['trace'];f=[s for s in trace if s.get('stepType')=='failure' and s.get('property')==doc['target']];assert f
    text=src.read_bytes().decode('utf8');a,b=region(task,text);frag=text[a:b]
    rows=[]
    for i,s in enumerate(trace):
        loc=s.get('sourceLocation',{});kind=s.get('stepType')
        if loc.get('file')!='program.i' or kind not in ('assignment','function-call','failure'):continue
        fun=s.get('function') or {}
        name=s.get('lhs') or (fun.get('displayName','') if isinstance(fun,dict) else str(fun))
        if len(name)>65 or '$' in name:continue
        val=s.get('value',{}).get('data','')
        if not isinstance(val,str) or len(val)>60:val=''
        rows.append(dict(index=i,thread=s.get('thread'),function=loc.get('function'),line=loc.get('line'),kind=kind,name=name,value=val))
    main=text[b:].strip()
    doc=dict(task=task,**{'program.c':frag},original_input_sha256=sha(src),contract=CONTRACT.get(task,STACK),
        property='CHECK( init(main()), LTL(G ! call(reach_error())) )',main_context=main[:2450],data_model=doc['meta']['data_model'],
        unwind=doc['meta']['bound'],sc=True,target=doc['target'],trace_steps=len(trace),counterexample=rows[-14:],
        failure=dict(thread=f[0].get('thread'),function=f[0]['sourceLocation']['function'],reason=f[0].get('reason',''),index=trace.index(f[0])))
    if task=='read_write_lock-2' and oracle.name=='P1':
        functional=oracle.parents[2]/'functional'/task/'P1'
        receipt=read(functional/'receipt.json')
        assert not receipt['passed'] and receipt['input_sha256']==sha(src)
        doc['independent_function_check']=(functional/'runtime.log').read_text().splitlines()
        doc['function_check_context']='Two readers acquired the lock concurrently, both completed and no writer ran between them. The reference count must return to zero to permit the next writer.'
    public_text(wire_text(doc),13000)
    return doc
