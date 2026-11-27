"""Describe actual CDCL ancestry and the D1 rejection witnesses for the leaves it uses."""
import argparse
from collections import Counter, defaultdict, deque
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import zip_longest
import gzip
import json
import mmap
from pathlib import Path
import struct
from urllib.parse import unquote

from prepare_d2 import clauses,metadata,occurrences,self_occurrences
from run_d1 import CASES
from run_stock import BASE,save


class Archive:
    def __init__(self,path):
        self.file=path.open("rb")
        self.data=mmap.mmap(self.file.fileno(),0,access=mmap.ACCESS_READ)
        self.sections=[]
        pos=12
        for stride in (16,4,8,16,12,8,12,4,4,4,4,4):
            n=struct.unpack_from("<I",self.data,pos)[0]
            self.sections.append(pos+4)
            pos+=4+n*stride

    def path_to_learning(self,leaf,pure_ids):
        offsets,children=self.sections[-2:]
        parent={leaf:None}
        work=deque([leaf])
        while work:
            v=work.popleft()
            if v in pure_ids:
                path=[]
                while v is not None:
                    path.append(v);v=parent[v]
                return path[::-1]
            lo,hi=struct.unpack_from("<II",self.data,offsets+4*v)
            for j in range(lo,hi):
                child=struct.unpack_from("<I",self.data,children+4*j)[0]
                if child not in parent:
                    parent[child]=v;work.append(child)
        return []


class Sites:
    def __init__(self,native):
        self.site={};self.ctx={};self.defs=defaultdict(list);self.bits=defaultdict(list)
        self.gates={};self.symbols=defaultdict(set)
        with gzip.open(native,"rt") as f:
            for line in f:
                if line.startswith(("C\t","TERM\t")):continue
                row=line.rstrip("\n").split("\t")
                t=row[0]
                if t=="S":
                    idx,key,status,fn,file,ln=row[1:]
                    self.site[idx]=(key,status,unquote(fn),unquote(file),int(ln) if ln.isdigit() else 0)
                elif t=="X":self.ctx[row[1]]=row[2]
                elif t=="V":
                    symbol,ctx,role,obj,typ,storage=row[1:]
                    site=self.site.get(self.ctx.get(ctx))
                    if site:
                        self.defs[symbol].append((site,role,obj,typ))
                        self.symbols[(site[0],role,obj,typ)].add(symbol)
                elif t=="A":
                    sym,typ,bit,lit=row[1:]
                    if int(lit)>=0:self.bits[int(lit)//2].append((sym,typ,int(bit)))
                elif t=="G":
                    self.gates[int(row[2])//2]=(row[1],tuple(map(int,row[3:])))


def inspect(case,run,checked,self_pair,out):
    d1=BASE/"reports/evidence/d1";pair=d1/"pairs"/case
    native=lambda s:d1/"runs/record"/case/s/"native.tsv.gz"
    var,matched=metadata(pair)
    old,new=Sites(native("P0")),Sites(native("P1"))
    spec=json.loads((BASE/"bench/manifest.json").read_text())[case]
    frozen={}
    for name,p0 in spec["inputs"]["P0"].items():
        base=BASE/"bench"/case
        lines=(base/p0).read_text().splitlines()
        newer=(base/spec["inputs"]["P1"][name]).read_text().splitlines()
        line_map={}
        for a,b,size in SequenceMatcher(None,lines,newer,autojunk=False).get_matching_blocks():
            line_map.update((a+i+1,b+i+1) for i in range(size))
        frozen[name]=(lines,line_map)

    @lru_cache(None)
    def blocker(v):
        path=[];seen=set()
        while v not in seen:
            seen.add(v)
            peer,role,why=var[v]
            if why.startswith("unmapped_gate_input:"):
                raw=int(why.split(":")[1])
                op,ins=old.gates[v]
                if raw not in ins:raise ValueError("gate witness not a native operand")
                path.append(dict(variable=v,op=op,input=raw))
                v=raw//2
            else:break
        _,role,why=var[v]
        unchanged=None
        for sym,typ,bit in old.bits.get(v,()):
            for site,def_role,obj,def_type in old.defs.get(sym,()):
                key,status,fn,file,ln=site
                if status!="unique" or file not in frozen:continue
                lines,lmap=frozen[file]
                if ln not in lmap:continue
                peers=new.symbols.get((key,def_role,obj,def_type),())
                # Require the same source line and semantic site on the new definition.
                peers=sorted(p for p in peers if any(s[3:]==(file,lmap[ln]) and s[1]=="unique"
                    for s,_,_,_ in new.defs[p]))
                if peers:
                    unchanged=dict(symbol=sym,bit=bit,native_bit_type=typ,operation_role=def_role,
                        function=fn,file=file,P0_line=ln,P1_line=lmap[ln],source=lines[ln-1].strip(),
                        peer_definition_count=len(peers),peer_examples=peers[:3])
                    break
            if unchanged:break
        return dict(gate_path=path,terminal_variable=v,terminal_role=role,terminal_reason=why,
                    bit_examples=old.bits.get(v,[])[:2],unchanged_source_site=unchanged)

    reached={int(n):(int(pid),int(rc),int(mask),int(fan),int(pfan)) for n,pid,rc,mask,fan,pfan in
             (l.split() for l in (checked/"used.tsv").open())}
    cats=[list(map(int,l.split())) for l in (checked/"learned.tsv").open()]
    pure={r[0] for r in cats if r[2]==0}
    archive=Archive(run/"knowledge.bin")
    rates=defaultdict(Counter);edges=defaultdict(Counter);terminal=Counter();examples={}
    for data,rec,self_rec in zip_longest(clauses(native("P0")),occurrences(pair),self_occurrences(self_pair)):
        scope,lits=data;seq,sc,key,why=rec
        if seq not in reached:continue
        pid,reach,mask,fan,pfan=reached[seq]
        if self_rec[:2]!=(seq,sc) or scope!=sc:raise ValueError("unaligned delta")
        gaps=[l for l in lits if l>=0 and var[l//2][0]<0]
        state="matched" if key in matched else "fully_mapped_absent" if key else "unknown"
        diagnostic=state
        if state=="unknown":
            roles={var[l//2][1] for l in gaps}
            group="aux_only" if roles=={"Aux"} else "aux_and_other" if "Aux" in roles else "other"
            diagnostic=("pair_only_" if self_rec[2] else "self_also_")+group
        groups=[("all_"+scope,fan)]+([("permanent_only_"+scope,pfan)] if reach&2 else [])
        for group,multiplicity in groups:
            rates[group][diagnostic]+=1;edges[group][diagnostic]+=multiplicity
        if scope!="B" or state=="matched":continue
        details=[]
        for lit in set(gaps):
            b=blocker(lit//2)
            for group,_ in groups:terminal[(group,b["terminal_reason"].split(":")[0])]+=1
            details.append((lit,b))
        if not reach&2:continue
        detail=next(((l,b) for l,b in details if b["unchanged_source_site"] and b["gate_path"]),None)
        detail=detail or next(((l,b) for l,b in details if b["unchanged_source_site"]),None)
        detail=detail or (details[0] if details else None)
        labels=[diagnostic]
        if detail and detail[1]["unchanged_source_site"]:
            labels.append("unchanged_frozen_line_gate" if detail[1]["gate_path"] else "unchanged_frozen_line_value")
        for label in labels:
            if label in examples:continue
            path=archive.path_to_learning(pid,pure)
            if not path:raise ValueError("used leaf lacks permanent Boolean descendant")
            examples[label]=dict(source_occurrence=seq,proof_id=pid,old_clause=lits,D1_key=key,D1_reason=why,
                self_comparable=bool(self_rec[2]),dependency_path=path,first_learned_descendant=path[-1],
                rejected_literal=detail[0] if detail else None,structural_witness=detail[1] if detail else None)
    proof_groups=Counter()
    for row in cats:
        if row[2]:continue
        mask=row[4]
        if not mask:label="survives"
        elif mask&1:
            label="lost_exact_content_and_mapping_gaps" if mask&6 else "lost_exact_content_only"
        else:
            keys="aux_only" if mask&6==2 else "other_only" if mask&6==4 else "aux_and_other"
            where="both" if mask&192==192 else "self_also" if mask&64 else "pair_only"
            label=where+"_"+keys
        proof_groups[label]+=1
    save(out,dict(distinct_used_occurrences=rates,direct_used_edge_counts=edges,
         terminal_reason_by_missing_literal={g:{k:n for (a,k),n in terminal.items() if a==g} for g in rates},
         complete_permanent_proof_outcomes=proof_groups,examples=examples))
    archive.data.close();archive.file.close()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("runs","checked","self_diffs","new_directory"):p.add_argument(name,type=Path)
    a=p.parse_args();a.new_directory.mkdir(parents=True,exist_ok=False)
    for c in CASES:inspect(c,a.runs/c/"on-1",a.checked/c,a.self_diffs/c,a.new_directory/(c+".json"))
