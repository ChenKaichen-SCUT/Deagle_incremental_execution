"""Bind signed RF/guard and eligible named scalar SSA bits to their typed dynamic definitions."""
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.model.identity import digest,read
from incdeagle.theory.context import freeze

def registry(folder,settings):
    ctx,graph=freeze(folder,settings,{'context':settings})
    full=read(folder/'full_model.json');goto=read(folder/'goto.json');visits=read(folder/'visits.json')
    by_var=defaultdict(list);data={}
    for key,(atom,raw,slot) in graph.by_key.items():
        if raw>=0:by_var[raw//2].append(('theory',digest(atom),raw&1))
    pool=full['ireps']
    @lru_cache(None)
    def term(i):
        if i is None:return None
        node=pool[i]
        return digest([node['id'],[(k,term(v)) for k,v in sorted(node.get('named',{}).items())],
                       [term(j) for j in node.get('sub',[])]])
    steps=defaultdict(list)
    for s in full['steps']:
        if s['kind']=='assignment' and s.get('local_symbol'):steps[s['local_symbol']].append(s)
    pcs={(r['function'],r['pc']):r for r in goto['instructions']}
    rows=0;scalar=0;private=Counter()
    for line in (folder/'bits.tsv').read_text().splitlines():
        name,kind,width,*raw=line.split('\t');rows+=1
        if kind not in ('signedbv','unsignedbv') or not width.isdecimal() or int(width)!=len(raw):
            private['unsupported_type_or_width']+=1;continue
        if len(steps[name])!=1:
            private['unconfirmed_definition']+=1;continue
        s=steps[name][0];i=s['visit'];pc=pcs.get((s['function'],s['pc']))
        if not i or pc is None or i>len(visits):
            private['unconfirmed_site']+=1;continue
        v=visits[i-1]
        definition=digest([name,kind,width,s['thread'],s['function'],s['pc'],
           [pc[k] for k in ('file','line','column','kind')],v['function'],v['pc'],v['thread'],v['frames'],
           [term(s.get(f)) for f in ('lhs','rhs','guard','original_lhs')]])
        scalar+=1
        for bit,x in enumerate(map(int,raw)):
            if x<0:continue
            label=digest([definition,bit]);by_var[x//2].append(('scalar',label,x&1))
        data[name]=definition
    groups={n:sorted(v) for n,v in by_var.items()}
    descriptions=[digest(v) for v in groups.values()]
    if len(set(descriptions))!=len(descriptions):raise ValueError('ambiguous variable alias group')
    orders=[s for s in (folder/'s8-graph.tsv').read_text().splitlines() if s.startswith('order\t')]
    return dict(graph=digest([ctx,orders]),groups=groups,bit_rows=rows,scalar_definitions=scalar,private=dict(private),
                sources=digest(data),theory_atoms=len(graph.by_key))

def decide(old,new,test='normal'):
    empty=dict(pairs=[],confirmed=0,renumbered_or_repolarized=0)
    if old['graph']!=new['graph']:return dict(reason='refuse_changed_graph',**empty)
    left=old['groups'];right=new['groups']
    reverse={digest(v):k for k,v in right.items()}
    candidate=[(a,reverse[digest(label)]) for a,label in left.items() if digest(label) in reverse]
    fixed=[(a,b) for a,b in candidate if a==b]
    if test=='bad-map' and len(fixed)>=2:fixed[0]=(fixed[0][0],fixed[1][1])
    if any(a!=b or left[a]!=right[b] for a,b in fixed) or len({b for _,b in fixed})!=len(fixed):
        return dict(reason='refuse_unverified_variable_mapping',**empty)
    # The conservative implementation binds an existing allocator literal only in its exact slot.
    # All remaining SAT meanings, including every unmapped auxiliary, are established from P1 alone.
    return dict(reason='keep' if fixed else 'refuse_no_stable_mapping',pairs=fixed,confirmed=len(fixed),
                renumbered_or_repolarized=len(candidate)-len(fixed))
