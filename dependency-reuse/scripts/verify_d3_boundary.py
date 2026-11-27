"""Check native SAT-boundary theory clauses against an independent D1 observer."""
import argparse
import mmap
import struct
from pathlib import Path


def verify(path, observer, *, native_fixture=False):
    counts = {"C": 0, "A": 0}
    with path.open("rb") as src, mmap.mmap(src.fileno(),0,access=mmap.ACCESS_READ) as data, observer.open("rb") as rows:
        if data[:8] not in (b"DEAGD3\x01\0",b"DEAGD3\x02\0") or data[-4:]!=b"END3":
            raise ValueError("incomplete D3 proof")
        sections=[]
        pos=12
        for width in (16,4,8,16,12,8,12,4,4,4,4,4,20,1):
            n=struct.unpack_from("<I",data,pos)[0]
            sections.append((pos+4,n))
            pos+=4+width*n
        if pos+24+18*8+8!=len(data) or (not native_fixture and not sections[13][1]):
            raise ValueError("missing native graph or invalid D3 section length")
        ops={}
        for i in range(sections[12][1]):
            id_,opcode=struct.unpack_from("<II",data,sections[12][0]+20*i)
            if opcode in (16,17) or opcode==18 and data[6]==2:ops[id_]=opcode
        lo=0
        for i in range(sections[0][1]):
            hi,end,kind,_=struct.unpack_from("<IIII",data,sections[0][0]+16*i)
            tag=None
            if kind==14:
                parent=struct.unpack_from("<I",data,sections[2][0]+8*(end-1))[0]
                tag={16:"C",17:"A",18:"A"}[ops[parent]]
            elif kind in (7,8):
                tag="C" if kind==7 else "A"
            if tag:
                row=rows.readline().split()
                clause=struct.unpack_from("<"+"i"*(hi-lo),data,sections[1][0]+4*lo)
                if not row or row[0]!=tag.encode() or tuple(map(int,row[1:]))!=clause:
                    raise ValueError(f"native theory boundary mismatch at ProofId {i}")
                counts[tag]+=1
            lo=hi
        if rows.readline():raise ValueError("unaccounted native theory observations")
    return counts


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("proof",type=Path)
    p.add_argument("observer",type=Path)
    args=p.parse_args()
    print(verify(args.proof,args.observer))
