"""Mutate native records and independent premise claims. Every fault must fail after its positive control passes."""
import argparse
import json
import shutil
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path
S=Path(__file__).resolve().parents[2]/"scripts";sys.path.insert(0,str(S))
from audit_d43b import Library,mark_dirty
from audit_d43c import slots,run_checker
from control_d43c import Structure,inverse,verify_models
from d43_project_support import check,digest,save

U32=struct.Struct("<I")


class SmallProof:
    """Uncompressed individual ancestors are intentional for tiny adversarial fixtures only."""
    def __init__(self,path):
        buf=path.read_bytes();at=12;sections=[]
        for width in (16,4,8,16,12,8,12,4,4,4,4,4,20,1):
            n,=U32.unpack_from(buf,at);start=at+4;at=start+n*width;sections.append(buf[start:at])
        self.nodes=list(struct.iter_unpack("<4I",sections[0]))
        words=list(x for x, in struct.iter_unpack("<i",sections[1]))
        edges=list(struct.iter_unpack("<Ii",sections[2]))
        self.inputs=[x[0] for x in struct.iter_unpack("<4I",sections[3])]
        self.births=list(struct.iter_unpack("<3I",sections[4]))
        self.evicted=list(struct.iter_unpack("<2I",sections[5]))
        self.facts={i:(o,a,b,c) for i,o,a,b,c in struct.iter_unpack("<IIiii",sections[12])}
        self.lits=[];self.parents=[];self.B=[];self.T=[]
        occ={v:k for k,v in enumerate(self.inputs)}
        le=pe=0
        for n,(hi,end,kind,flags) in enumerate(self.nodes):
            ps=[p for p,_ in edges[pe:end]];self.parents.append(ps);self.lits.append(words[le:hi])
            self.B.append({occ[n]} if kind==1 else set().union(*(self.B[p] for p in ps)))
            self.T.append({self.facts[n]} if kind==12 else set().union(*(self.T[p] for p in ps)))
            le=hi;pe=end

    def check_births(self,path):
        lib=Library(path);permanent=0
        for record,(node,_,_) in zip(lib.births(),self.births,strict=True):
            i,flags,actual,b,t=record
            f=self.nodes[node][3]
            q=4*bool(f&2)+8*bool(f&5)
            check(flags&12==q,"wrong query/unknown disposition")
            if q:
                check(actual is None,"scoped conclusion exported");continue
            permanent+=1
            expected=self.lits[node]
            check(actual==struct.pack("<"+"i"*len(expected),*expected),"different signed birth")
            for j in self.B[node]:
                check(lib.observed(0,j),"missing exact Boolean UsedLeaf "+str(j+1))
                need=1<<lib.slots[0][lib.b[j]]
                check(b&need,"missing Boolean ancestor bit at birth "+str(i))
            for fact in self.T[node]:
                j,g=lib.t[fact]
                check(lib.observed(1,j),"missing exact Theory UsedLeaf")
                check(t&(1<<lib.slots[1][g]),"missing theory ancestor bit")
        return permanent

    def minimization_only(self):
        for i,(n,u,m) in enumerate(self.births):
            ps=self.parents[n]
            exclusive=set().union(*(self.B[p] for p in ps[u:u+m]))-set().union(*(self.B[p] for p in ps[:u]+ps[u+m:]))
            if exclusive:return i,min(exclusive)
        raise ValueError("missing successful minimization witness")


def frames(buf):
    at=8
    while at<len(buf):
        code=chr(U32.unpack_from(buf,at)[0])
        if code=="E":break
        if code=="B":
            fields=struct.unpack_from("<10I",buf,at);end=at+40+4*fields[-1]+256
        elif code=="Q":
            fields=struct.unpack_from("<6I",buf,at);end=at+24+4*fields[-1]
        elif code=="D":fields=struct.unpack_from("<4I",buf,at);end=at+16
        elif code=="X":fields=struct.unpack_from("<2I",buf,at);end=at+8
        else:raise ValueError("invalid observation")
        yield code,at,fields
        at=end


def clean_spec(path):
    rows=[]
    for line in path.read_text().splitlines():
        z=line.split()
        if z and z[0]=="B":
            rows.append(tuple(sorted({2*abs(int(v))+int(int(v)<0) for v in z[1:]})))
    return set(rows)


def dirty_check(lib,g,target,claimed):
    # Recompute all changed Boolean occurrences against the actual target corpus.
    pool=clean_spec(target/"spec")
    states={tuple(map(int,a[1:5])):a[5] for line in (target/"decl").read_text().splitlines()
            if (a:=line.split()) and a[0]=="D"}
    badb={i for i,n in enumerate(g.inputs) if g.nodes[n][2]==1 and tuple(sorted(set(g.lits[n]))) not in pool}
    badt={k for k in lib.t if states[k]!="M"}
    expected=[set(),set()]
    for i in badb:mark_dirty(expected[0],lib.slots[0][lib.b[i]],lib.observed(0,i),False)
    for key in badt:
        i,group=lib.t[key];mark_dirty(expected[1],lib.slots[1][group],lib.observed(1,i),False)
    if claimed is not None:check(expected==claimed,"missing or spurious Dirty slot")
    kept=exact=0
    masks=[sum(1<<s for s in d) for d in expected]
    for record,(node,_,_) in zip(lib.births(),g.births,strict=True):
        _,flags,_,b,t=record
        if flags&12:continue
        ok=not (g.B[node]&badb or g.T[node]&badt)
        admit=not (b&masks[0] or t&masks[1])
        check(not admit or ok,"unsound candidate after input change")
        exact+=ok;kept+=admit
    return expected,dict(exact=exact,dense=kept,changed_B=len(badb),changed_T=len(badt))


class Campaign:
    def __init__(self,fixtures,out,checker):
        self.fixtures=fixtures;self.out=out;self.checker=checker;self.results={}
        self.out.mkdir(parents=True,exist_ok=False)
    def reject(self,name,action,why,metadata=None):
        try:action()
        except (ValueError,KeyError,struct.error,subprocess.CalledProcessError) as exc:
            msg=(exc.stderr or "") if isinstance(exc,subprocess.CalledProcessError) else str(exc)
            check(any(w in msg for w in why),"unexpected rejection for "+name+": "+msg)
            self.results[name]=dict(disposition="REJECTED",observed=msg.strip(),witness=metadata or {})
        else:raise ValueError("fault escaped: "+name)
    def corrupt(self,name,source,buf,test,why,**evidence):
        check(bytes(buf)!=source.read_bytes(),"unchanged mutant")
        target=self.out/(name+".bin");target.write_bytes(buf)
        self.reject(name,lambda:test(target),why,dict(source=source.name,mutant_sha256=digest(target),**evidence))
    def learning(self):
        fixtures=self.fixtures
        for case,label in (("direct","eliminated_B_ancestor"),("root-chain","explicit_root_unit"),
                           ("minimize-gc","successful_minimization"),("same-slot","second_same_slot_UsedLeaf"),
                           ("minimize-gc","stale_tag_after_eviction")):
            d=fixtures/case;path=d/"dense.bin";lib=Library(path);g=SmallProof(d/"proof.bin")
            check(g.check_births(path)>0,"expected a permanent birth");buf=bytearray(path.read_bytes())
            if label=="successful_minimization":i,j=g.minimization_only()
            elif label=="stale_tag_after_eviction":
                by_id={n:i for i,(n,_,_) in enumerate(g.births)}
                pair=next((i,by_id[ancestor]) for ancestor,last in g.evicted for i,(n,_,_) in enumerate(g.births)
                          if n>last and g.B[n]-g.B[ancestor])
                i,old=pair;j=min(g.B[g.births[i][0]]-g.B[g.births[old][0]])
                stats=dict(line.split() for line in (d/"dense.bin.stats").read_text().splitlines())
                check(int(stats["GC"]) and int(stats["recycled_clause_slots"]),"no native GC or recycle")
            else:
                def wanted(i,j):
                    unit=g.lits[g.inputs[j]];clause=g.lits[g.births[i][0]]
                    if label=="explicit_root_unit":return len(unit)==1 and unit[0]//2 not in {x//2 for x in clause}
                    if label=="eliminated_B_ancestor":return any(l//2 not in {x//2 for x in clause} for l in unit)
                    return len(g.B[g.births[i][0]])>1 and sum(lib.b[k]==lib.b[j] for k in g.B[g.births[i][0]])>=2
                i,j=next((i,j) for i,(n,_,_) in enumerate(g.births) for j in sorted(g.B[n]) if wanted(i,j))
            bit=lib.slots[0][lib.b[j]];pos=lib.offsets[i];n=U32.unpack_from(buf,pos+5)[0];start=pos+10+n*4
            if label=="second_same_slot_UsedLeaf":
                at=len(buf)-16-len(lib.bits[1])-4-len(lib.bits[0]);buf[at+j//8]&=~(1<<(j%8))
                why=["missing exact Boolean UsedLeaf"]
            elif label=="stale_tag_after_eviction":
                previous=lib.offsets[old];previous+=10+4*U32.unpack_from(buf,previous+5)[0]
                buf[start:start+128]=buf[previous:previous+128];why=["missing Boolean ancestor"]
            else:buf[start+bit//8]&=~(1<<(bit%8));why=["missing Boolean ancestor"]
            self.corrupt(label,path,buf,g.check_births,why,case=case,birth=i+1,occurrence=j+1,slot=bit)

    def scoped_and_theory(self):
        for case,label in (("Q","query_forged_permanent"),("dynamic-CO","indirect_unknown_forged_permanent")):
            d=self.fixtures/case;path=d/"dense.bin";lib=Library(path);g=SmallProof(d/"proof.bin");g.check_births(path)
            i,flags,lits,b,t=next(v for v in reversed(list(lib.births(d/"dense.bin.scoped"))) if v[1]&12)
            at=lib.offsets[i-1]
            record=struct.pack("<cIIB",b"L",i,len(lits)//4,flags&3)+lits+b.to_bytes(128,"little")+t.to_bytes(128,"little")
            buf=path.read_bytes()
            self.corrupt(label,path,buf[:at]+record+buf[at+6:],g.check_births,["wrong query/unknown disposition"],case=case,birth=i)
        d=self.fixtures/"shared-theory";path=d/"dense.bin";lib=Library(path);g=SmallProof(d/"proof.bin")
        g.check_births(path)
        node=next(n for n,_,_ in g.births if not g.nodes[n][3]&7 and len(g.T[n])>1)
        facts=sorted(g.T[node]);groups={lib.t[k][1] for k in facts};check(len(groups)==1,"need two used theory leaves in a shared slot")
        j=lib.t[facts[1]][0];buf=bytearray(path.read_bytes());at=len(buf)-16-len(lib.bits[1]);buf[at+j//8]&=~(1<<(j%8))
        self.corrupt("second_same_slot_theory_UsedLeaf",path,buf,g.check_births,["missing exact Theory UsedLeaf"],
                     case=d.name,leaf=facts[1],other_leaf=facts[0],shared_group=next(iter(groups)))
        d=self.fixtures/"deferred-RF";path=d/"proof.bin";buf=bytearray(path.read_bytes());g=SmallProof(path)
        stream=bytearray((d/"boundaries.bin.cert").read_bytes());_,at,f=next(x for x in frames(stream) if x[0]=="B")
        lemma=f[4];check(f[-1]>=2,"need a conditional clause")
        litbase=16+len(g.nodes)*16+4;offset=litbase+4*(g.nodes[lemma-1][0]+1);buf[offset]^=1
        stream[at+44]^=1
        _,q,_=next(x for x in frames(stream) if x[0]=="Q");stream[q+28]^=1
        side=self.out/"forged-discharge.cert";side.write_bytes(stream)
        tr=bytearray((d/"boundaries.bin").read_bytes())
        pos=0
        while U32.unpack_from(tr,pos)[0]!=8:pos+=8+4*U32.unpack_from(tr,pos+4)[0]
        tr[pos+12]^=1
        trace=self.out/"forged-discharge.trace";trace.write_bytes(tr)
        def check_forgery(proof):return run_checker(self.checker,proof,d/"decl",d/"T-slots.tsv",trace,side)
        self.corrupt("forged_discharge_all_literal_streams_agree",path,buf,check_forgery,
                     ["discharged theory clause differs"],case=d.name,Audit_ProofID=lemma,changed_literal_index=1)

    def boundaries(self,actual_case,actual_decl,actual_slots):
        for name,case,op in (("conditionless_PO","empty-PO-APO",1),("conditionless_APO","empty-PO-APO",2),
                             ("opaque_CO_certified","dynamic-CO",None),("missing_source_certified","missing-source",None),
                             ("queue_reason_mixed","deferred-RF",None),("binding_native_polarity","unit-guard",None),
                             ("boundary_proofID_mixed","deferred-guard",None)):
            d=self.fixtures/case;side=d/"boundaries.bin.cert";buf=bytearray(side.read_bytes())
            g=SmallProof(d/"proof.bin");lib=Library(d/"dense.bin")
            _,at,fields=next(f for f in frames(buf) if f[0]=="B")
            raw=at+40+4*fields[-1];rule=fields[5]
            def valid(p):return run_checker(self.checker,d/"proof.bin",d/"decl",d/"T-slots.tsv",d/"boundaries.bin",p)
            valid(side)
            if op:
                check(fields[-1]==0,"not a condition-free native conflict")
                fact=next(k for k in sorted(g.T[rule]) if k[0]==op)
                bit=lib.slots[1][lib.t[fact][1]]
                for offset in (0,128):buf[raw+offset+bit//8]&=~(1<<(bit%8))
                why=["missing projected theory premise"]
            elif name.endswith("certified"):U32.pack_into(buf,at+32,2);why=["uncertified reason admitted"]
            elif name=="binding_native_polarity":
                buf[at+40]^=1;why=["native literal stream differs"]
            elif name=="queue_reason_mixed":
                _,q,f=next(v for v in frames(buf) if v[0]=="Q");U32.pack_into(buf,q+12,fields[5]+1)
                why=["queued reason/ProofID/literal mismatch"]
            else:U32.pack_into(buf,at+16,fields[4]-1);why=["different Audit ProofID"]
            self.corrupt(name,side,buf,valid,why,case=case,lemma=fields[4],rule=rule)
        p=actual_case/"boundaries.bin.cert";buf=bytearray(p.read_bytes())
        _,at,field=next(x for x in frames(buf) if x[0]=="D")
        U32.pack_into(buf,at+4,field[1]+1)
        def actual(changed):
            return run_checker(self.checker,actual_case/"proof.bin",actual_decl,actual_slots,actual_case/"boundaries.bin",changed)
        self.corrupt("dedup_overwrote_first_ticket",p,buf,actual,["duplicate replaced pending reason"],case="fib_updates_8",ticket=field[1])
        buf=bytearray(p.read_bytes())
        _,at,field=next(x for x in frames(buf) if x[0]=="B" and x[2][6]>1)
        U32.pack_into(buf,at+24,field[6]-1)
        self.corrupt("stale_queue_ticket",p,buf,actual,["map::at","queued reason/ProofID/literal mismatch"],case="fib_updates_8",ticket=field[6])

    def changed(self,micro):
        results={}
        for case,chg in (("direct","B"),("direct","T"),("direct","B+T"),("direct","unrelated"),("root-chain","removed"),
                         ("minimize-gc","hidden-parent"),("block","split"),("block","merge"),("domain","expanded")):
            d=self.fixtures/case;lib=Library(d/"dense.bin");g=SmallProof(d/"proof.bin")
            expected,row=dirty_check(lib,g,micro/case/chg,None)
            results[case+"/"+chg]=row
            if case=="root-chain" or (case=="direct" and chg=="T"):
                bad=[s.copy() for s in expected];dom=0 if case=="root-chain" else 1;erased=bad[dom].pop()
                self.reject("omitted_Dirty"+"BT"[dom],lambda:dirty_check(lib,g,micro/case/chg,bad),
                            ["missing or spurious Dirty slot"],dict(case=case,change=chg,erased_slot=erased))
        save(self.out/"changed.json",results)

    def archive(self,case):
        path=case/"dense.bin";lib=Library(path);original=path.read_bytes()
        for name,at,v,why in (("wrong_schema",0,ord("Z"),"compact format"),("wrong_capacity",12,1,"compact format"),
                              ("incomplete_footer",len(original)-1,0,"invalid footer")):
            buf=bytearray(original);buf[at]=v;self.corrupt(name,path,buf,Library,[why])
        self.corrupt("truncated_archive",path,original[:-23],Library,["truncated compact archive"])
        buf=bytearray(original);directory=20
        # All births in this Boolean fixture are permanent.
        for _,_,lits,_,_ in lib.births():directory+=10+len(lits)+256
        check(original[directory:directory+1]==b"D","group table offset")
        first=directory+5;second=first+6+U32.unpack_from(original,first+2)[0]
        struct.pack_into("<H",buf,second,0);self.corrupt("duplicate_independent_slot",path,buf,Library,["persisted slot/domain"])


def run():
    p=argparse.ArgumentParser(description=__doc__)
    for a in ("fixtures","micro","real_Fibonacci","declarations","slots","checker","out"):p.add_argument(a,type=Path)
    x=p.parse_args();c=Campaign(x.fixtures,x.out,x.checker)
    c.learning();c.boundaries(x.real_Fibonacci,x.declarations,x.slots);c.changed(x.micro);c.archive(x.fixtures/"root-chain")
    save(x.out/"rejections.json",c.results)
    print(len(c.results),"injected faults independently rejected")

if __name__=="__main__":run()
