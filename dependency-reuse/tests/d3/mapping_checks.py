"""Finite positive and negative controls for structural gate and bit identities."""
import argparse
import subprocess
import tempfile
from pathlib import Path
import sys

scripts=Path(__file__).resolve().parents[2]/"scripts"
sys.path.insert(0,str(scripts))
from d1_identity import Keys, apply_layouts
from collections import defaultdict


def layouts(signature,width=2,observed=None,storage="static",prefix=None,bit=None):
    observed=width if observed is None else observed
    prefix=width if prefix is None else prefix
    rows=defaultdict(list,LAYOUT=[("9",signature,str(prefix))],
        V_LAYOUT=[("word","9")],A_LAYOUT=[("word","9",str(width))],
        V=[("word","21","read","object","",storage)],
        A=[("word","",str(i),str(8+2*i)) for i in range(observed)])
    apply_layouts(rows,keys)
    return rows["V"][0][4] if bit is None else rows["A"][bit][1]


def run(engine,folder,label,p1_inputs=(6,2),symmetric=False,query=False):
    path=folder/label
    path.mkdir()
    a=path/"a";b=path/"b"
    a.write_text("G\tand\t8\t2\t4\nG\tand\t10\t4\t2\nG\tor\t12\t8\t6\n"
        +"C\tB\t8\t6\nC\tB\t10\t"+("6" if symmetric else "7")+"\nN\t10\nQUERY\n")
    op="Q" if query else "B"
    x,y=p1_inputs
    b.write_text(f"G\tand\t16\t{y}\t{x}\nG\tand\t15\t{x}\t{y}\nG\tor\t18\t4\t15\n"
        +f"C\t{op}\t15\t4\nC\t{op}\t16\t"+("4" if symmetric else "5")+"\nN\t10\nQUERY\n")
    m=path/"m";n=path/"n"
    m.write_text("1 11 0 Value -\n2 12 0 Value -\n3 13 0 Value -\n")
    n.write_text("3 11 0 Value -\n1 12 0 Value -\n2 13 0 Value -\n")
    subprocess.run([engine,a,b,m,n,path,"--d3-mapping"],check=True)
    return {int(r[1]):int(r[2]) for r in map(str.split,(path/"variables.tsv").read_text().splitlines()) if r[0]=="0"}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("boolean_diff",type=Path)
    engine=p.parse_args().boolean_diff.resolve()
    keys=Keys()
    assert layouts("struct:a16,b16")==layouts("struct:a16,b16")
    assert layouts("struct:a16,b16")!=layouts("struct:b16,a16")
    assert layouts("same",2)!=layouts("same",3)
    assert not layouts("partial",3,2) and not layouts("partial",2,3)
    assert not layouts("instance",2,storage="instance")
    assert layouts("integer-then-pointer",4,prefix=2,bit=1)
    assert not layouts("integer-then-pointer",4,prefix=2,bit=2)
    assert not layouts("pointer-view",4,prefix=0)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        r=run(engine,root,"renumber-and-invert")
        assert [r[i] for i in (4,5,6)]==[15,16,18],r
        for label,kwargs in [("same-uses",dict(symmetric=True)),("different-function",dict(p1_inputs=(7,2))),
                             ("query-uses",dict(query=True))]:
            r=run(engine,root,label,**kwargs)
            assert all(r[i]<0 for i in (4,5,6)),r
    print("Mapping checks passed: complete aggregate layout/width, unchanged gate function, signed injectivity, ambiguous and query-only uses.")
