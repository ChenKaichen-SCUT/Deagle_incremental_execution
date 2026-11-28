"""Fail-closed live loading, shared overflow slots, the real import boundary and file-access controls."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
S=Path(__file__).resolve().parents[2]/"scripts";sys.path.insert(0,str(S))
from compact43 import DenseLibrary,require
from d43_prepare import dirty,choose
from cases42 import load
from diff_d1 import digest
from run_stock import run,save


def layout(data):
    pos=20;last=first=scope=None
    while data[pos:pos+1]!=b"D":
        if data[pos:pos+1]==b"S":
            scope=pos;pos+=6
        else:
            if first is None:first=pos
            last=pos;pos+=266+4*struct.unpack_from("<I",data,pos+5)[0]
    p=pos+5;second=p+6+struct.unpack_from("<I",data,p+2)[0]
    for _ in range(2):
        groups=struct.unpack_from("<I",data,pos+1)[0] if _==0 else struct.unpack_from("<I",data,pos)[0]
        pos+=5 if _==0 else 4
        for i in range(groups):pos+=6+struct.unpack_from("<I",data,pos+2)[0]
    nb=struct.unpack_from("<I",data,pos)[0];pos+=4+nb*4
    nt=struct.unpack_from("<I",data,pos)[0];pos+=4+nt*20
    return first,last,scope,second,pos


def negatives(exe,tools,source,out):
    case="fib_updates_8";spec=load()[case];data=(source/"dense.bin").read_bytes()
    first,last,scope,second,used=layout(data)
    def mutate(pos,fmt,value):
        def apply(buf):struct.pack_into(fmt,buf,pos,value)
        return apply
    configs={
        "format":("incompatible producer",lambda r:r.update(format="D42-SC-v1")),
        "producer":("incompatible producer",lambda r:r.update(elf="0"*64)),
        "rules":("incompatible producer",lambda r:r.update(rules="different-rules")),
        "tools":("incompatible producer",lambda r:r["tools"].update({"compact-structure":"0"*64})),
        "memory-model":("incompatible ABI or memory model",lambda r:r["argv"].__setitem__(r["argv"].index("--mm")+1,"tso")),
        "ABI":("incompatible native configuration",lambda r:r["argv"].__setitem__(r["argv"].index("--64"),"--32")),
        "audit-payload":("incompatible producer",lambda r:r["files"].update({"proof.bin":{}}))}
    corrupt={
        "ordinal":("discontinuous birth ordinal",mutate(first+1,"<I",99)),
        "late-literal":("birth literal outside producer model",mutate(last+10,"<i",0x70000000)),
        "scope":("invalid scoped disposition",mutate(scope+5,"<B",1)),
        "old-slot":("old dense slot",mutate(second,"<H",0)),
        "used-length":("UsedLeaf length",mutate(used,"<I",9)),
        "capacity":("compact format or capacity",mutate(12,"<I",2048)),
        "truncated":("truncated compact file",lambda buf:buf.pop()),
        "out-of-registry-tag":("tag scope or unobserved slot",None)}
    outcomes={};sha=digest(exe)
    for label in [*configs,*corrupt,"sealed-bytes","stale-receipt","no-recorder"]:
        d=out/label;lib=d/"P0/native";lib.mkdir(parents=True)
        artifact=d/"P1/native";artifact.mkdir(parents=True)
        receipt=json.loads((source/"library.json").read_bytes())
        (lib/"model.tsv").symlink_to(source/"model.tsv")
        if label in configs:
            reason,inject=configs[label];inject(receipt)
        if label in corrupt or label=="sealed-bytes":
            buf=bytearray(data)
            if label=="sealed-bytes":
                reason="P0 payload checksum";buf[-1]^=1
            else:
                reason,inject=corrupt[label]
                if inject:inject(buf)
                else:
                    n=struct.unpack_from("<I",buf,last+5)[0];buf[last+10+4*n+127]|=128
            (lib/"dense.bin").write_bytes(buf)
            if label!="sealed-bytes":
                receipt["files"]["dense.bin"]=dict(bytes=len(buf),sha256=hashlib.sha256(buf).hexdigest())
        else:(lib/"dense.bin").symlink_to(source/"dense.bin")
        save(lib/"library.json",receipt);seal=digest(lib/"library.json")
        (lib/"library.sha256").write_text(seal+"\n")
        if label=="stale-receipt":reason="P0 seal checksum";seal="0"*64
        save(artifact/"control43.json",dict(case=case,library_sha256=seal))
        opts=["--d43-load",str(lib),"--d4-mode","reuse","--d4-out",str(artifact),"--d4-tools",str(tools),"--d41-identities"]
        if label=="no-recorder":
            opts.extend(["--d3-proof",str(d/"never-proof.bin")]);reason="D4 load requires"
        run(exe,{**spec,"argv":opts+spec["argv"]},case,"P1",d/"P1",sha)
        meta=json.loads((d/"P1/run.json").read_bytes())
        err="".join(p.read_text() for p in (d/"P1/stderr",artifact/"prepare.stderr",d/"P1/stdout") if p.is_file())
        require(meta["exit_code"] not in (0,10) and reason in err and not meta["timed_out"],"unexpected rejection "+label)
        require(not any((artifact/f).exists() for f in ("ready.tsv","imports.tsv","hits.tsv")) and
                not (d/"never-proof.bin").exists(),"partial installation or recorder")
        outcomes[label]=dict(expected=reason,exit=meta["exit_code"],published=False)
    save(out/"rejections.json",outcomes)


def overflow(out):
    out.mkdir(parents=True)
    word=lambda i:struct.pack("<I",i)
    buf=bytearray(b"D43DNS2\0"+struct.pack("<III",0x01020304,1024,1023))
    mask=(1<<1023).to_bytes(128,"little")
    for i in range(1,515):
        buf+=b"L"+struct.pack("<IIBi",i,1,3,2)+mask+mask
    buf+=b"S"+struct.pack("<IB",515,4)+b"S"+struct.pack("<IB",516,8)+b"D"
    for side in "BT":
        buf+=word(1025)
        for i in range(1025):
            key=(["B","gate","and",i] if side=="B" else ["T","decl","Schema",[i,0,"w","x","static"]])
            raw=json.dumps(key,separators=(",",":")).encode()
            buf+=struct.pack("<HI",min(i,1023),len(raw))+raw
    buf+=word(2)+struct.pack("<II",1023,1024)+word(2)
    for i in (1023,1024):buf+=struct.pack("<4iI",5,i,-1,-1,i)
    buf+=word(1)+b"\x01"+word(1)+b"\x01"+word(516)+word(0)+b"ENDDENSE"
    (out/"dense.bin").write_bytes(buf);lib=DenseLibrary(buf);flags=lib.occurrence_flags()
    lib.validate_payload(2,flags);mu=[-1,3];results={}
    for name,peer,state,expected in (("complete",2,"M",514),("unseen-B",0,"M",0),("unseen-T",2,"U",0)):
        d=out/name;d.mkdir();(d/"input-matches.tsv").write_text("occurrence\tP1_permanent_occurrence\n1\t1\n2\t%d\n"%peer)
        cert={(5,1023,-1,-1):"M",(5,1024,-1,-1):state}
        masks,_=dirty(lib,flags,cert,mu,d);result=choose(lib,mu,masks,2,d)
        require(result["eligible"]==expected and result["chosen"]==min(512,expected),"overflow/cap")
        lines=(d/"selected.tmp").read_text().splitlines()[1:]
        require(all(line==f"{j}\tM\t1\t3" for j,line in enumerate(lines,1)),"ordinal selection or signed literal")
        results[name]=dict(eligible=expected,selected=len(lines),dirty=[m.bit_count() for m in masks])
    save(out/"results.json",results)


def traced(exe,tools,source,out,strace):
    c="fib_updates_8";spec=load()[c];d=out/"native";d.mkdir(parents=True)
    save(d/"control43.json",dict(case=c,library_sha256=digest(source/"library.json")))
    log=out/"open.trace"
    opts=[str(x) for x in ("-f","-qq","-s","2048","-e","trace=open,openat,openat2,execve","-o",log,exe,
        "--d43-load",source,"--d4-mode","reuse","--d4-out",d,"--d4-tools",tools,"--d41-identities")]
    run(strace,{**spec,"argv":opts+spec["argv"]},c,"P1",out,digest(strace))
    meta=json.loads((out/"run.json").read_bytes());require(meta["exit_code"]==0 and (d/"imports.tsv").is_file(),"traced live run")
    calls=log.read_text().splitlines();files=set()
    for line in calls:
        if "open" not in line or "execve(" in line:continue
        for p in re.findall(r'"([^"]+)"',line):
            path=Path(p)
            require(path.name not in ("proof.bin","proof.bin.quality.tsv","effective-map.tsv.old","dense.bin.scoped")
                    and "/reports/evidence/" not in p and not any(k in p for k in ("/d42/","/d43b/","/d43c/")),"proof or frozen mapping I/O")
            if path.parent==source:files.add(path.name)
    require(files=={"model.tsv","dense.bin","library.sha256","library.json"},"unexpected old knowledge file")
    save(out/"access.json",dict(open_trace_sha256=digest(log),P0_library_files=sorted(files),archived_proof_reads=0,
                                old_mapping_reads=0,selected=json.loads((d/"policy.json").read_bytes())["chosen"]))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("exe","tools","production","out","strace"):p.add_argument(key,type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    overflow(a.out/"overflow");negatives(a.exe,a.tools,a.production,a.out/"invalid")
    traced(a.exe,a.tools,a.production,a.out/"traced",a.strace)
