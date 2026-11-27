"""Verify native slot overflow, same-bit observations and full supports across real miniSAT GC."""
from pathlib import Path
import argparse,json,struct,subprocess,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from audit_d43b import Library,mark_dirty
from d43_project_support import check,save


def stress(directory):
    lib=Library(directory/"dense.bin")
    data=(directory/"proof.bin").read_bytes()
    at=12;sections=[]
    for width in (16,4,8,16,12):
        n,=struct.unpack_from("<I",data,at);sections.append((at+4,n));at+=4+width*n
    nodes,lits,edges=sections[:3];n=nodes[1]
    support=[frozenset() for _ in range(n)]
    occ=0;last_edge=last_lit=0;born=iter(lib.births());count=0
    for i,(hi,end,k,flags) in enumerate(struct.iter_unpack("<4I",data[nodes[0]:nodes[0]+16*n])):
        if k==1:occ+=1;support[i]=frozenset((occ,))
        else:
            support[i]=frozenset().union(*(support[struct.unpack_from("<I",data,edges[0]+j*8)[0]]
                                            for j in range(last_edge,end)))
        if k==6:
            count+=1;seq,flag,actual,mask,theory=next(born)
            expected=sum(1<<g for g in {lib.slots[0][lib.b[o-1]] for o in support[i]})
            check(seq==count and actual==data[lits[0]+4*last_lit:lits[0]+4*hi] and
                  flag==1 and mask==expected and not theory and all(lib.observed(0,o-1) for o in support[i]),
                  "stress proof differs after GC/minimization")
        last_edge,last_lit=end,hi
    check(next(born,None) is None,"missing native birth")
    return count


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("binary",type=Path);p.add_argument("out",type=Path)
    a=p.parse_args();results={}
    for mode in ("observe","0","1","2"):
        directory=a.out/mode;directory.mkdir(parents=True,exist_ok=False)
        with (directory/"stdout").open("w") as out:subprocess.run([a.binary,mode,directory],stdout=out,check=True)
        if mode!="observe":
            results["native_stress_min_"+mode]=stress(directory);continue
        lib=Library(directory/"dense.bin")
        check([len(k) for k in lib.keys]==[1026,1026],"all distinct overflow keys retained")
        check(all(s[:1023]==list(range(1023)) and s[1023:]==[1023]*3 for s in lib.slots),"unstable group slots")
        check([i+1 for i in range(len(lib.b)) if lib.observed(0,i)]==[1,2],"Boolean raw observations")
        check(lib.b[:3].tolist()==[0,0,0],"Boolean aliases")
        observed=[f for f,(i,g) in lib.t.items() if lib.observed(1,i)]
        check(observed==[(0,-1,-1,-1),(1,0,1,-1),(5,1024,-1,-1)],"Theory observations")
        missing=(5,1025,-1,-1);used=(5,1024,-1,-1)
        def bit(f):return 1<<lib.slots[1][lib.t[f][1]]
        check(bit(missing)&bit(used) and lib.t[missing][1]!=lib.t[used][1],"overflow false acceptance")
        dirty=set()
        mark_dirty(dirty,lib.slots[1][lib.t[missing][1]],False,False)
        check(dirty=={1023} and bool(bit(used)&sum(1<<s for s in dirty)),"unconfirmed overflow member survived")
        mark_dirty(dirty,0,False,False)
        check(dirty=={1023},"unused independent slot was dirtied")
        results["unobserved_unmatched_overflow_member_invalidates_sibling"]=True
        results["overflow_groups_each_domain"]=3
        results["read_two_raw_leaves_same_bit"]=True;results["registered_unused_declaration_excluded"]=True
    save(a.out/"checks.json",results)
if __name__=="__main__":main()
