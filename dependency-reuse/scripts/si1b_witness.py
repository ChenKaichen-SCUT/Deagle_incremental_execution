"""Resolve published witnesses independently back to both native local value streams."""
from collections import Counter
import csv
from functools import lru_cache
import gzip
import json
from si1b_catalog import Model, Wire, Registry, check


def immutable(x):
    return tuple(map(immutable,x)) if isinstance(x,list) else x

class Reader:
    def __init__(self,model,keys):
        self.m=model
        self.keys=keys
    @lru_cache(maxsize=None)
    def frames(self,key):
        row=self.keys[key]
        if row[0]=="conversion-root":
            fs=self.m.roots.get(key,())
            check(all(self.m.template[i]==(row[2],row[3]) and row[3] for i in fs),"root recipe")
            return tuple(fs)
        check(row[0]=="operand","unexpected template route")
        parents=self.frames(row[1]);edge,domain=row[2]
        fs={child for p in parents for child in self.m.children[p].get((edge,domain),())}
        check(all(self.m.template[i][0]==domain and self.m.template[i][1] for i in fs),"child recipe")
        return tuple(fs)
    def values(self,key):
        m=self.m;row=self.keys[key]
        if row[0] in ("outer","Guard","RF-write-read"):return m.bind.get(key,set())
        ids=self.frames(row[1])
        if row[0]=="returned":
            bit,width=row[2:]
            return {m.result[i][bit] for i in ids if len(m.result[i])==width}
        check(row[0]=="lowering-role","unsupported witness")
        return {v for i in ids for v in m.roles[i].get(row[2],())}
    def recipe(self,key):
        r=self.keys[key]
        if r[0] in ("returned","lowering-role"):return self.frames(r[1])
        return ()

def verify(folder,source,out):
    with gzip.open(out/"typed-keys.json.gz","rt") as f:keys=[immutable(x) for x in json.load(f)]
    reg=Registry();reg.rows=keys.copy();reg.index={k:i for i,k in enumerate(keys) if i}
    doc=json.loads((source/"source-catalog.json").read_bytes())
    models=[Model(Wire(folder/v,source),reg,doc,i) for i,v in enumerate(("P0","P1"))]
    check(len(reg.rows)==len(keys),"sealed typed registry incomplete")
    readers=[Reader(m,keys) for m in models];seen=[set(),set()];roles=Counter();examples={}
    with gzip.open(out/"direct-map.tsv.gz","rt") as f:
        for item in csv.DictReader(f,delimiter="\t"):
            v,y,k=map(int,(item["old_variable"],item["positive_image"],item["witness_key"]))
            signed_values=[reader.values(k) for reader in readers]
            check(all(len(x)==1 for x in signed_values),"witness not single-valued")
            l,r=[next(iter(s)) for s in signed_values]
            check(l>=2 and r>=2 and l//2==v and r^(l&1)==y,"witness does not justify signed pair")
            for bag,atom in zip(seen,(v,y//2)):
                check(atom not in bag,"duplicate image/domain");bag.add(atom)
            frames=[rd.recipe(k) for rd in readers]
            if any(frames):
                recipes=[{m.template[i] for i in ids} for m,ids in zip(models,frames)]
                check(len(recipes[0])==1 and recipes[0]==recipes[1],"mixed template generation")
            left=models[0].interface.get(v,set());right=models[1].interface.get(y//2,set())
            check(all(t for _,t,_ in left|right) and {(n,t,s^(y&1)) for n,t,s in left}==right,"interface override")
            label=keys[k][0]
            if label=="lowering-role":label+="/"+keys[k][2][1]
            roles[label]+=1
            examples.setdefault(label,dict(old=v,positive_image=y,typed_witness=k,native_local_values=[l,r],
                 templates=[list(z) for z in frames]))
    return dict(accepted=len(seen[0]),wrong=0,roles=roles,examples=examples)
