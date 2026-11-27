"""Negative slice checks against an independently replayed full Fibonacci proof."""
import argparse
from pathlib import Path
import struct
import subprocess
import json

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("checker","full","compact","output"):p.add_argument(k,type=Path)
    a=p.parse_args();a.output.mkdir(parents=True)
    src=a.compact.read_bytes();assert src[:6]==b"DEAGDC"
    sections=[];pos=12
    for size in (16,4,8,16,12,8,12,4,4,4,4,4,20):
        n=struct.unpack_from("<I",src,pos)[0];sections.append((pos+4,n));pos+=4+n*size
    nodes,ls,edges,inputs=sections[:4]
    id_=next(i for i in range(1,nodes[1]) if struct.unpack_from("<I",src,nodes[0]+16*i+8)[0]==15)
    checks={"lost-signed-pivot":edges[0]+4,"changed-conclusion-or-premise":ls[0],"changed-input-ordinal":inputs[0]+12,
            "cleared-retirement-scope":nodes[0]+16*id_+12}
    result={}
    for label,at in checks.items():
        bad=bytearray(src)
        old=struct.unpack_from("<I",bad,at)[0];altered=0 if label=="cleared-retirement-scope" else old^1
        assert altered!=old
        struct.pack_into("<I",bad,at,altered);path=a.output/(label+".bin");path.write_bytes(bad)
        run=subprocess.run([a.checker,a.full,path],capture_output=True,text=True)
        assert run.returncode==1 and run.stderr.strip(),(label,run)
        result[label]=dict(byte_offset=at,old_word=old,new_word=altered,rejection=run.stderr.strip())
    (a.output/"rejections.json").write_text(json.dumps(result,indent=2)+"\n")
    print("four damaged compact projections rejected")

if __name__=="__main__":main()
