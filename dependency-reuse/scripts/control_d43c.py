"""Audit controlled full-model bijections, original directory interpretation and ordinal selection, offline."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
import struct
from audit_d43b import Library, mark_dirty, seals
from cases42 import load
from d43_project_support import check, digest, save
from identity42 import permute

FIXED={"DEAGLE-D1","K","S","SITE41","X","E","V","LAYOUT","V_LAYOUT","EVENT_LAYOUT","TERM","H",
       "VALUE_DEF","F","QUERY","TARGET","A_LAYOUT","END","READY"}
STRUCT={"K","NODE","IN","OUT","MEMBER","EDGE","GUARD"}


def inverse(mapping, size):
    check(set(mapping)==set(range(1,size)),"variable domain mismatch")
    reverse={}
    for old,raw in mapping.items():
        atom,sign=divmod(raw,2)
        check(0<atom<size and atom not in reverse,"non-injective or out-of-range mapping")
        reverse[atom]=2*old+sign
    return reverse


def literal(raw, mapping):
    if raw in (-1,-2):return raw
    check(raw>=2 and raw//2 in mapping,"unmapped literal")
    return mapping[raw//2]^(raw&1)


def original_row(line, variables, events):
    """Read the transported fixture in old coordinates. Fields outside atom/event namespaces stay literal."""
    row=line.rstrip("\n").split("\t");tag=row[0]
    if tag in FIXED:return row
    lits=[];nodes=[]
    if tag in ("C","G","N"):lits=range(2,len(row))
    elif tag in ("A","GUARD"):lits=[len(row)-1]
    elif tag=="EDGE":lits=[4,7];nodes=[5,6]
    elif tag=="NODE":nodes=[1,6]
    elif tag in ("IN","OUT","MEMBER"):nodes=[1,2]
    elif tag=="CO":nodes=[1,2];lits=range(3,len(row))
    else:raise ValueError("unrecognized model row "+tag)
    for i in lits:row[i]=str(literal(int(row[i]),variables))
    for i in nodes:
        n=int(row[i])
        if n>=0:row[i]=str(events[n])
    return row


class Structure:
    def __init__(self):
        self.nodes={};self.names={};self.members=defaultdict(set);self.within=set();self.reverse=set()
        self.edges=defaultdict(set);self.guards=defaultdict(set);self.config=None;self.domains=defaultdict(set)

    def add(self,v):
        kind=v[0]
        if kind=="K":
            check(self.config is None,"multiple semantic configurations");self.config=tuple(v[1:])
        elif kind=="NODE":
            i,name,addr,read,write,parent=v[1:];i=int(i)
            check(i not in self.nodes and name not in self.names,"duplicate event")
            self.nodes[i]=(name,int(addr),read,write,int(parent));self.names[name]=i
        elif kind=="MEMBER":self.members[int(v[1])].add(int(v[2]))
        elif kind=="IN":self.reverse.add((int(v[2]),int(v[1])))
        elif kind=="OUT":self.within.add((int(v[1]),int(v[2])))
        elif kind=="GUARD":self.guards[v[1]].add(int(v[2]))
        elif kind=="EDGE":
            _,op,a,b,raw,u,w,binding=v
            self.edges[op,a,b,int(raw)].add((int(u),int(w),int(binding)))
            if op=="rf":self.domains[b].add((a,int(raw)))

    def fact(self, key):
        op,a,b,c=key
        if op==0:
            check(self.config is not None,"rule config missing");return self.config
        name,addr,read,write,parent=self.nodes[a]
        if op in (1,2,3):
            other=self.nodes[b][0];raw=c if op==3 else -1
            entry=self.edges.get((("po","apo","rf")[op-1],name,other,raw))
            check(bool(entry),"order or RF binding missing")
            return name,other,raw,frozenset(entry)
        if op==4:
            check(c in self.guards.get(name,()),"Guard binding missing");return name,c
        if op==5:return self.nodes[a]
        if op==6:
            check(addr==self.nodes[b][1],"same-address condition missing");return addr
        check(op==7 and a==parent and self.members[a],"block representative missing")
        members=self.members[a]
        directions=frozenset((i,j) for i,j in self.within if i in members)
        check(all(j in members for i,j in directions) and directions==frozenset(
            (i,j) for i,j in self.reverse if i in members),"block direction inconsistency")
        return frozenset(members),directions

    def domain(self,read):
        return frozenset(self.domains.get(read,()))


def compatible(old_config, new_config, old_args, new_args):
    def model_args(args):
        check("--deagle-closure" in args and args.count("--mm")==1,"missing explicit Closure model")
        abi=[v for v in args if v in ("--32","--64")]
        check(len(abi)==1,"ambiguous ABI")
        return abi[0],args[args.index("--mm")+1]
    check(old_config==new_config and model_args(old_args)==model_args(new_args),
          "incompatible ABI, memory model or theory semantics")


def claimed_preserved(old, new, keys=(), domains=()):
    for key in keys:
        check(old.fact(key)==new.fact(key),"changed structural premise")
    for read in domains:
        check(old.domain(read)==new.domain(read),"changed complete candidate domain")


def verify_models(old,new,forward,eventmap,library):
    reverse=inverse(forward,len(forward)+1)
    back={n:o for o,n in eventmap.items()};check(len(back)==len(eventmap),"non-injective event map")
    g,h=Structure(),Structure();occurrences=0;scopes=defaultdict(int);dirty=[set(),set()]
    rows=0
    with old.open() as a,new.open() as b:
        for left,right in zip(a,b,strict=True):
            p=left.rstrip("\n").split("\t");q=original_row(right,reverse,back)
            rows+=1;tag=p[0]
            if tag=="C":
                entry=library.b[occurrences];observed=library.observed(0,occurrences)
                if p[1]=="B":
                    check(entry<len(library.keys[0]),"invalid Boolean premise directory")
                    mark_dirty(dirty[0],library.slots[0][entry],observed,p==q)
                else:check(entry>=0xfffffffe and not observed,"query or unknown marked permanent")
                occurrences+=1;scopes[p[1]]+=1
            if tag in STRUCT:g.add(p);h.add(q)
            check(p==q,"changed typed "+tag+" row "+str(rows))
    check(occurrences==len(library.b),"input directory length")
    check(g.within==g.reverse and h.within==h.reverse,"inconsistent block graph")
    for key,(index,group) in library.t.items():
        preserved=g.fact(key)==h.fact(key)
        mark_dirty(dirty[1],library.slots[1][group],library.observed(1,index),preserved)
        check(preserved,"registered theory premise changed")
    claimed_preserved(g,h,domains=set(g.domains)|set(h.domains))
    check(not any(dirty),"nonempty Dirty under controlled isomorphism")
    return dict(typed_rows=rows,original_occurrences=occurrences,original_scopes=dict(scopes),
                theory_declarations=len(library.t),RF_domains=len(g.domains),DirtyB=0,DirtyT=0)


def one(case, model, library, out):
    size=0;events=[]
    with model.open() as f:
        for s in f:
            if s.startswith("N\t"):size=int(s.split()[1])
            elif s.startswith("NODE\t"):events.append(int(s.split()[1]))
    results={};ordinals=None
    old_args=json.loads((model.parent/"library.json").read_bytes())["argv"]
    def config(file):
        with file.open() as f:return next(r.rstrip("\n") for r in f if r.startswith("K\t"))
    for label in ("identity","unsigned","signed"):
        dest=out/label;dest.mkdir(parents=True,exist_ok=False);rng=random.Random(420187)
        vals=list(range(1,size));ev=sorted(events)
        if label!="identity":rng.shuffle(vals);rng.shuffle(ev)
        forward={i:2*j+(rng.getrandbits(1) if label=="signed" else 0) for i,j in enumerate(vals,1)}
        emap=dict(zip(sorted(events),ev));back=inverse(forward,size)
        target=model
        if label!="identity":
            target=dest/"renamed.tsv";permute(model,target,forward,emap)
        compatible(config(model),config(target),old_args,old_args)
        result=verify_models(model,target,forward,emap,library)
        eligible=[];rejected=defaultdict(int);selected=[];hasher=hashlib.sha256()
        for i,flags,lits,bits,tbits in library.births():
            if flags&12:
                check(lits is None,"scope payload exposed");rejected["unknown" if flags&8 else "query"]+=1
                continue
            renamed=[literal(x,forward) for (x,) in struct.iter_unpack("<i",lits)]
            check(all(literal(y,back)==x for y,(x,) in zip(renamed,struct.iter_unpack("<i",lits))),"polarity round trip")
            eligible.append(i)
            hasher.update(struct.pack("<II",i,len(renamed))+b"".join(struct.pack("<i",x) for x in renamed))
            if len(selected)<512:selected.append(i)
        if ordinals is None:ordinals=eligible
        else:check(eligible==ordinals,"controlled admissible ordinals changed")
        (dest/"selected.tsv").write_text("ordinal\n"+"".join(f"{i}\n" for i in selected))
        result.update(eligible=len(eligible),selected_under_cap=len(selected),rejected=dict(rejected),
            translated_conclusion_sha256=hasher.hexdigest(),source_sha256=digest(model),model_sha256=digest(target),
            old_directory_unchanged=True,negative_images=sum(v&1 for v in forward.values()),
            native_variables=size-1,events=len(events),selection_sha256=digest(dest/"selected.tsv"))
        save(dest/"control.json",result);results[label]=result
    return results


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("B_matrix",type=Path);p.add_argument("output",type=Path)
    a=p.parse_args();all_cases={}
    for case in load():
        d=a.B_matrix/case/"compact";seals(d)
        all_cases[case]=one(case,d/"native/model.tsv",Library(d/"native/dense.bin"),a.output/case)
        print(case,all_cases[case]["signed"]["eligible"],flush=True)
    for label in ("identity","unsigned","signed"):
        check(sum(v[label]["eligible"] for v in all_cases.values())==97901,"permanent denominator")
        check(sum(v[label]["eligible"] for c,v in all_cases.items() if c!="fib-snapshot-11")==43295,"repair denominator")
    save(a.output/"controls.json",all_cases)
