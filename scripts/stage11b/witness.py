"""Construct and independently check an explicit SC completion of a returned bounded SAT model."""
from collections import defaultdict
from pathlib import Path
import json
class Unknown(Exception):pass
def check(d,max_states=40000):
    fields=(d/'answer.txt').read_text().split()
    rc,n=map(int,fields[:2])
    if rc:return {'status':'NO_SAT_MODEL'}
    model=json.loads((d/'full_model.json').read_bytes());decl=json.loads((d/'native-bindings.json').read_bytes())
    values=list(map(int,fields[2:2+n]));rank={}
    offset=2+n;size=int(fields[offset]);offset+=1
    for i in range(size):rank[fields[offset+2*i]]=int(fields[offset+2*i+1])
    def lit(q):
        if q<0:return q==-1
        if values[q//2] not in (0,1):raise Unknown('undefined model literal')
        return values[q//2]==(q&1)
    pool=model['ireps'];known={}
    scalar={}
    for line in (d/'bits.tsv').read_text().splitlines():
        name,kind,width,*raw=line.split('\t')
        if kind in ('signedbv','unsignedbv') and width.isdecimal() and int(width)==len(raw):
            scalar[name]=(kind,tuple(map(int,raw)))
    def bv(i,seen=frozenset()):
        if i in seen:raise Unknown('cyclic bitvector')
        t=pool[i];op=t['id'];typ=pool[t['named']['type']]
        kind=typ['id']
        if kind not in ('signedbv','unsignedbv'):raise Unknown('unsupported scalar '+kind)
        width=int(pool[typ['named']['width']]['id']);mask=(1<<width)-1
        if op=='symbol':
            name=pool[t['named']['identifier']]['id']
            if name not in scalar:
                if name not in rhs:raise Unknown('missing bit binding')
                return bv(rhs[name],seen|{i})
            sk,bits=scalar[name]
            if (sk,len(bits))!=(kind,width):raise Unknown('bitvector type mismatch')
            answer=sum(int(lit(raw))<<bit for bit,raw in enumerate(bits))
        elif op=='constant':answer=int(pool[t['named']['value']]['id'],16)
        elif op=='if':
            c,a,b=t['sub'];answer=bv(a if val(c) else b,seen|{i})
        elif op=='typecast':answer=bv(t['sub'][0],seen|{i})
        else:raise Unknown('unsupported bitvector operation '+op)
        answer&=mask
        return answer-(1<<width) if kind=='signedbv' and answer>>(width-1) else answer
    def remember(i,v):
        if known.setdefault(i,v)!=v:raise Unknown('opposite guard aliases')
        term=pool[i]
        if term['id']=='not':remember(term['sub'][0],not v)
    gs={r['local_symbol']:r for r in model['oc_guards']}
    for g in decl['guards']:remember(gs[g['event']]['guard'],lit(g['x']))
    rhs={s['local_symbol']:s['rhs'] for s in model['steps'] if s['kind']=='assignment' and s.get('local_symbol') and s.get('rhs') is not None}
    raw_rf=defaultdict(list)
    for e in decl['edges']:
        if e['kind']=='rf' and lit(e['x']):raw_rf[e['to']].append(e['from'])
    def cell(i,index,seen):
        if i in seen:raise Unknown('cyclic array explanation')
        t=pool[i];op=t['id'];data=t.get('sub',[]);seen=seen|{i}
        if op=='array_of':return val(data[0],seen)
        if op=='with' and len(data)==3:
            return val(data[2],seen) if bv(data[1])==index else cell(data[0],index,seen)
        if op=='symbol':
            name=pool[t['named']['identifier']]['id']
            if name not in rhs and len(raw_rf[name])==1:name=raw_rf[name][0]
            if name in rhs:return cell(rhs[name],index,seen)
        raise Unknown('unexplained array read '+op)
    def val(i,seen=frozenset()):
        if i in known:return known[i]
        if i in seen:raise Unknown('cyclic Boolean guard')
        t=pool[i];op=t['id'];data=t.get('sub',[])
        if op=='constant':
            v=pool[t['named']['value']]['id']
            if pool[t['named']['type']]['id']!='bool' or v not in ('1','true','0','false'):raise Unknown('non-Boolean guard constant')
            return v in ('1','true')
        if op=='not':return not val(data[0],seen|{i})
        if op=='index':return cell(data[0],bv(data[1]),seen|{i})
        if op in ('=','notequal','>=','<=','>','<'):
            lhs,rhs_id=data
            if pool[pool[lhs]['named']['type']]['id']=='bool':
                a,b=val(lhs,seen|{i}),val(rhs_id,seen|{i})
            else:a,b=bv(lhs),bv(rhs_id)
            return {'=':a==b,'notequal':a!=b,'>=':a>=b,'<=':a<=b,'>':a>b,'<':a<b}[op]
        if op in ('and','or'):
            unknown=[]
            for p in data:
                try:v=val(p,seen|{i})
                except Unknown as ex:unknown.append(str(ex));continue
                if op=='and' and not v:return False
                if op=='or' and v:return True
            if not unknown:return op=='and'
            raise Unknown(op+'('+','.join(unknown)+')')
        if op=='symbol':
            nm=pool[t['named']['identifier']]['id']
            if nm in rhs:return val(rhs[nm],seen|{i})
        raise Unknown('unconfirmed guard expression '+op)
    events={s['oc_name']:s for s in model['steps'] if s.get('oc_name')}
    if set(events)!=set(decl['addresses']):raise Unknown('unmapped event')
    live={k for k,e in events.items() if val(e['guard'])}
    groups={k:frozenset([k]) for k in events}
    pred=defaultdict(set);selected=defaultdict(list)
    for e in decl['edges']:
        a,b,k=e['from'],e['to'],e['kind']
        if k in ('po','apo'):pred[b].add(a)
        elif k=='rf':
            if b in live and lit(e['x']):selected[b].append(a)
        else:raise Unknown('unmodeled relation '+k)
        if k=='apo':
            group=groups[a]|groups[b]
            for g in group:groups[g]=group
    # Project transitive structure across disabled intermediates.
    for a in events:
        for b in events:
            if a in pred[b]:pred[b]|=pred[a]
    pred={k:pred[k]&live for k in live}
    source={};address=decl['addresses']
    for r in live:
        if events[r]['kind']!='read':continue
        if len(selected[r])!=1:raise Unknown('read has '+str(len(selected[r]))+' selected RF sources')
        w=selected[r][0]
        if w not in live or events[w]['kind']!='write' or address[w]!=address[r]:raise Unknown('invalid read source')
        source[r]=w;pred[r].add(w)
    group={k:groups[k]&live for k in live}
    def legal(e,left,last):
        if pred[e]&left:return False
        if e in source:return last.get(address[e])==source[e]
        if events[e]['kind']=='write':
            # Cannot overwrite the unique selected write before remaining consumers have read it.
            prior=last.get(address[e])
            if prior is not None and any(r in left and w==prior for r,w in source.items()):return False
        return True
    count=0;unsat=set()
    def visit(left,last,block):
        nonlocal count
        if not left:return []
        state=(left,tuple(sorted(last.items())),block)
        if state in unsat:return None
        count+=1
        if count>max_states:raise Unknown('SC schedule search budget')
        for e in sorted(left if not block else block,key=lambda v:(rank.get(v,0),v)):
            if not legal(e,left,last):continue
            memo=last
            if events[e]['kind']=='write':memo={**last,address[e]:e}
            rest=left-{e}
            path=visit(rest,memo,group[e]&rest)
            if path is not None:return [e]+path
        unsat.add(state);return None
    order=visit(frozenset(live),{},frozenset())
    if order is None:return {'status':'NO_ORDER_FOR_RETURNED_ASSIGNMENT','states':count}
    # Recheck the complete witness without DFS/pruning, including full per-address write order.
    pos={v:i for i,v in enumerate(order)};last={};ws=defaultdict(list)
    assert set(order)==live and all(pos[a]<pos[b] for b in live for a in pred[b])
    for block in set(group.values()):
        idx=sorted(pos[v] for v in block);assert idx==list(range(idx[0],idx[-1]+1))
    for e in order:
        if e in source:assert last[address[e]]==source[e]
        if events[e]['kind']=='write':last[address[e]]=e;ws[address[e]].append(e)
    return dict(status='EXPLICIT_SC_ORDER',states=count,order=order,rf=source,ws=ws)
def result(d):
    try:return check(d)
    except (Unknown,RecursionError,OSError,ValueError,KeyError,IndexError,AssertionError) as exc:
        return dict(status='UNCONFIRMED',reason=f'{type(exc).__name__}: {exc}')
