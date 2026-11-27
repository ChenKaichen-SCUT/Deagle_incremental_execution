"""Independent native emissions, branch lifetime, local-premise mutations and signed mapping negatives."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

here=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("d4fixture",here.parent/"d4/check.py")
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
sys.path.insert(0,str(here.parents[1]/"scripts"))
from d1_identity import Keys
from d41_identity import pair_sites
from verify_d3_boundary import verify
from audit_d4 import numbers


def sites(forms):
    return {"S":[(str(i),key,quality,"function") for i,(key,quality,shape) in enumerate(forms)],
            "SITE41":[(str(i),shape) for i,(_,_,shape) in enumerate(forms)]}


def identities():
    anchor=lambda k:(k,"unique",k)
    def site(shape):return ("unresolved","ambiguous",shape)
    a,b=anchor("left"),anchor("right")
    def pairs(old,new):return pair_sites(sites(old),sites(new),Keys())
    u,v=pairs([a,site("i32 write"),site("bool guard"),b],[a,site("extra"),site("i32 write"),site("bool guard"),b])
    assert u["1"]==v["2"] and u["2"]==v["3"]
    u,v=pairs([a,site("write"),site("write"),b],[a,site("write"),b])
    assert not u and not v
    assert not pairs([a,site("i32 write"),b],[a,site("i64 write"),b])[0]
    assert not pairs([a,site("g(x)"),b],[a,site("g(!x)"),b])[0]
    assert not pairs([a,site("write"),b],[b,site("write"),a])[0]
    u,v=pairs([a,site("loop"),site("loop"),b],[a,site("loop"),site("loop"),b])
    assert u==v and len(set(u.values()))==2


def corrupt(src,out,checker):
    data=(src/"record/proof.bin").read_bytes()
    pos=12;sections=[]
    for width in (16,4,8,16,12,8,12,4,4,4,4,4,20):
        n=struct.unpack_from("<I",data,pos)[0];sections.append((pos+4,n));pos+=4+width*n
    at=next(sections[12][0]+20*j for j in range(sections[12][1])
            if struct.unpack_from("<I",data,sections[12][0]+20*j+4)[0]==18)
    node,op,a,b,r=struct.unpack_from("<IIiii",data,at)
    parent0=struct.unpack_from("<I",data,sections[0][0]+16*(node-1)+4)[0]
    addr=sections[2][0]+8*parent0
    checks={"repeated-event":(at+12,a),"wrong-first-order":(addr,struct.unpack_from("<I",data,addr+8)[0]),
            "rf-instead-of-guard":(addr+24,struct.unpack_from("<I",data,addr+16)[0]),
            "wrong-same-address":(addr+40,struct.unpack_from("<I",data,addr+32)[0])}
    result={}
    for label,(where,value) in checks.items():
        d=out/label;d.mkdir();bad=bytearray(data);struct.pack_into("<I",bad,where,value);(d/"bad.bin").write_bytes(bad)
        cmd=[checker,d/"bad.bin",src/"same/inputs",src/"same/map",src/"oracle/native-learns.tsv",src/"same/decl",d]
        rejection=subprocess.run(cmd,capture_output=True,text=True)
        assert rejection.returncode==1 and rejection.stderr.strip(),label
        result[label]=rejection.stderr.strip()
    stream=(src/"oracle/native-theory.tsv").read_text().splitlines()
    row=next(i for i,s in enumerate(stream) if s.startswith("A\t"))
    cells=stream[row].split();cells[1]=str(int(cells[1])^1);stream[row]="\t".join(cells)
    bad=out/"flipped-observer.tsv";bad.write_text("\n".join(stream)+"\n")
    try:verify(src/"record/proof.bin",bad,native_fixture=True)
    except ValueError as e:result["actual_clause_polarity"]=str(e)
    else:raise AssertionError("changed native assignment accepted")
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("select","tools","output"):p.add_argument(k,type=Path)
    a=p.parse_args();select,tools,root=[v.resolve() for v in vars(a).values()]
    root.mkdir(parents=True);identities()
    m=fixture.mixed
    seed=m.benchmark("triplet",[("rf",m.W,m.R,5),("po",m.W,m.X,0),("po",m.X,m.R,0)],[(m.W,0),(m.X,7)])
    results={}
    for tag,activation,root_units,guard in (("deferred-RF",[5],[],7),("deferred-guard",[7],[],7),
                   ("immediate-RF",[],[(5,)],7),("immediate-guard",[],[(7,)],7),("unit-guard",[],[],0)):
        z=deepcopy(seed);z["assumptions"]=activation;z["clauses"]+=root_units;z["guards"][m.X]=guard
        base=root/tag;ns=fixture.p0(tools,z,base)
        native=verify(base/"record/proof.bin",base/"oracle/native-theory.tsv",native_fixture=True)
        for ch in ("same","first-order","second-order","rf-binding","guard","unrelated"):
            y=deepcopy(z)
            if ch=="first-order":y["edges"].pop(1)
            if ch=="second-order":y["edges"].pop(2)
            if ch=="rf-binding":y["edges"][0]=("rf",m.W,m.R,-5)
            if ch=="guard":y["guards"][m.X]=-7 if guard else 7
            if ch=="unrelated":y["clauses"].append((8,))
            out=base/ch;res=fixture.delta(select,tools,z,y,base,out,ns)
            metrics=numbers(out/"metrics.tsv");res.update(triplets=metrics.get("lemma_op_18",0),boundaries=native)
            results[tag+"/"+ch]=res
        same=results[tag+"/same"];assert same["triplets"]>0,(tag,same)
        assert results[tag+"/unrelated"]["reasons_retained"]==same["reasons_retained"]
        for changed in ("first-order","second-order","rf-binding","guard"):
            assert results[tag+"/"+changed]["reasons_retained"]<same["reasons_retained"],(tag,changed)
    results["reject"]=corrupt(root/"deferred-RF",root,tools/"check")
    (root/"results.json").write_text(json.dumps(results,indent=2)+"\n")
    print("30 native triplet transfers, finite model checks, six site controls, five corruptions passed")


if __name__=="__main__":main()
