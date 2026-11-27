"""Lossless content-addressed packaging and restoration for D4 process and proof artifacts."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

CHUNK=4<<20


def sha(data):return hashlib.sha256(data).hexdigest()


def safe(root,name):
    path=(root/name).resolve()
    if root not in path.parents:raise ValueError("invalid archive path "+str(name))
    return path


def pack(dest,sources):
    (dest/"objects").mkdir(parents=True,exist_ok=False)
    files={}
    for arg in sources:
        label,src=arg.split("=",1)
        base=Path(src).resolve(strict=True)
        names=[(label,base)] if base.is_file() else [(label+"/"+p.relative_to(base).as_posix(),p) for p in sorted(base.rglob("*")) if p.is_file()]
        for name,p in names:
            safe(dest,name)
            if name in files:raise ValueError("duplicate archive key "+name)
            total=hashlib.sha256();blocks=[]
            with p.open("rb") as f:
                for data in iter(lambda:f.read(CHUNK),b""):
                    block=sha(data);blocks.append(block);total.update(data)
                    obj=dest/"objects"/(block+".gz")
                    if not obj.is_file():obj.write_bytes(gzip.compress(data,compresslevel=5,mtime=0))
            files[name]=dict(bytes=p.stat().st_size,sha256=total.hexdigest(),chunks=blocks)
    index=dict(format="D4-raw-v1",chunk_bytes=CHUNK,files=files)
    (dest/"files.json").write_text(json.dumps(index,indent=2)+"\n")


def read(root,prefix,dest):
    index=json.loads((root/"files.json").read_text())
    if index["format"]!="D4-raw-v1" or index["chunk_bytes"]!=CHUNK:raise ValueError("archive format")
    n=size=0
    for name,entry in index["files"].items():
        if prefix and name!=prefix and not name.startswith(prefix.rstrip("/")+"/"):continue
        total=hashlib.sha256();length=0
        if dest:
            target=safe(dest,name);target.parent.mkdir(parents=True,exist_ok=True)
            output=target.open("xb")
        else:output=None
        try:
            for h in entry["chunks"]:
                if len(h)!=64 or any(c not in "0123456789abcdef" for c in h):raise ValueError("chunk key")
                data=gzip.decompress((root/"objects"/(h+".gz")).read_bytes())
                if sha(data)!=h:raise ValueError("damaged chunk "+h)
                total.update(data);length+=len(data)
                if output:output.write(data)
        finally:
            if output:output.close()
        if length!=entry["bytes"] or total.hexdigest()!=entry["sha256"]:raise ValueError("damaged file "+name)
        n+=1;size+=length
    if not n:raise ValueError("empty archive selection")
    print(f"{n} files, {size} original bytes verified")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    subs=p.add_subparsers(dest="action",required=True)
    put=subs.add_parser("pack");put.add_argument("archive",type=Path);put.add_argument("sources",nargs="+",metavar="LABEL=PATH")
    for action in ("verify","restore"):
        parser=subs.add_parser(action);parser.add_argument("archive",type=Path)
        if action=="restore":parser.add_argument("new_directory",type=Path)
        parser.add_argument("--prefix",default="")
    a=p.parse_args();root=a.archive.resolve()
    if a.action=="pack":pack(root,a.sources)
    else:
        out=a.new_directory.resolve() if a.action=="restore" else None
        if out:out.mkdir(parents=True,exist_ok=False)
        read(root,a.prefix,out)


if __name__=="__main__":main()
