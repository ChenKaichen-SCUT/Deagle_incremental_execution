"""Source-checked finite SC interleaver for the two frozen read/write lock versions."""
import hashlib
import re
from collections import Counter, deque
from dataclasses import dataclass

ROOT_DIGEST = {"P1":"dd98405c728a760da56688c8e3153ab085899b582cefa08e43058c1deb3637bf",
               "P2":"bfce38d4c6dd8b83b0e7ccf5dd860317721211d6230963b5cb3c4897eb3546d2"}
THREADS = ("W1","R1","W2","R2")
WRITER = ("acquire W","x=3","w=0")
READER = ("acquire R","l=x","y=l","ly=y","lx=x","assert ly==lx")


def instructions(path,version):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ROOT_DIGEST[version]:
        raise ValueError("unreviewed program")
    source = raw.decode()
    def body(signature):
        return " ".join(source.split(signature,1)[1].split("}",1)[0].split())
    assert "int w=0, r=0, x, y;" in source
    assert "if(!cond) {abort();" in body("void assume_abort_if_not(int cond) {")
    assert "__assert_fail" in body("void reach_error() {")
    assert body("void __VERIFIER_atomic_take_write_lock() {") == "assume_abort_if_not(w==0 && r==0); w = 1;"
    assert body("void __VERIFIER_atomic_take_read_lock() {") == "assume_abort_if_not(w==0); r = r+1;"
    assert body("void *writer(void *arg) {") == "__VERIFIER_atomic_take_write_lock(); x = 3; w = 0; return 0;"
    reader = body("void *reader(void *arg) {")
    prefix = ("int l; __VERIFIER_atomic_take_read_lock(); l = x; y = l; int ly = y; "
              "int lx = x; if (!(ly == lx)) ERROR: reach_error(); ")
    tails = {"l = r-1; r = l; return 0;":("l=r-1","r=l"),
             "__VERIFIER_atomic_release_read_lock(); return 0;":("atomic r=r-1",)}
    assert reader.startswith(prefix)
    tail = tails[reader[len(prefix):]]
    if len(tail)==1:
        assert body("void __VERIFIER_atomic_release_read_lock() {") == "r = r-1;"
    main = body("int main() {")
    assert re.findall(r"pthread_create\(&t(\d), 0, (writer|reader), 0\);",main)==[
        ("1","writer"),("2","reader"),("3","writer"),("4","reader")]
    assert re.findall(r"pthread_join\(t(\d), 0\);",main)==["1","2","3","4"]
    return (WRITER,READER+tail,WRITER,READER+tail)


@dataclass(frozen=True)
class State:
    pcs: tuple = (0,0,0,0)
    mem: tuple = (0,0,0,0)  # w, r, x, y
    local: tuple = ((0,0,0),)*4  # l, ly, lx; dead locals reset to avoid duplicate futures


def step(st,i,op):
    w,r,x,y = st.mem
    l,ly,lx = st.local[i]
    if op=="acquire W":
        if w or r:
            return None
        w=1
    elif op=="x=3": x=3
    elif op=="w=0": w=0
    elif op=="acquire R":
        if w:
            return None
        r+=1
    elif op=="l=x": l=x
    elif op=="y=l": y,l=l,0
    elif op=="ly=y": ly=y
    elif op=="lx=x": lx=x
    elif op=="assert ly==lx":
        if ly!=lx:
            return "failure"
        ly,lx=0,0
    elif op=="l=r-1": l=r-1
    elif op=="r=l": r,l=l,0
    elif op=="atomic r=r-1": r-=1
    else: raise ValueError(op)
    loc=list(st.local)
    loc[i]=(l,ly,lx)
    pcs=list(st.pcs)
    pcs[i]+=1
    return State(tuple(pcs),(w,r,x,y),tuple(loc))


def explore(program):
    first=State()
    parent={first:None}
    queue=deque([first])
    counts=Counter()
    bad=None
    invariant_violations=0
    while queue:
        st=queue.popleft()
        readers=sum(0<pc<len(ops) for i,(pc,ops) in enumerate(zip(st.pcs,program)) if i in (1,3))
        writers=sum(0<st.pcs[i]<len(WRITER) for i in (0,2))
        if st.mem[1]!=readers or st.mem[0]!=writers or (readers and writers):
            invariant_violations+=1
        if all(pc==len(ops) for pc,ops in zip(st.pcs,program)):
            counts["finished_states"]+=1
        for i,(pc,ops) in enumerate(zip(st.pcs,program)):
            if pc==len(ops):
                continue
            op=ops[pc]
            nxt=step(st,i,op)
            if nxt is None:
                counts["guard_disabled_edges"]+=1
                continue
            counts["enabled_edges"]+=1
            if nxt=="failure":
                counts["assert_failure_edges"]+=1
                if bad is None:
                    bad=(st,i)
            elif nxt not in parent:
                parent[nxt]=(st,i)
                queue.append(nxt)
    witness=[]
    if bad:
        current,i=bad
        path=[(current,i)]
        while parent[current] is not None:
            current,i=parent[current]
            path.append((current,i))
        for st,i in reversed(path):
            witness.append({"thread":THREADS[i],"operation":program[i][st.pcs[i]],
                            "before":{"w":st.mem[0],"r":st.mem[1],"x":st.mem[2],"y":st.mem[3]},
                            "local_before_l_ly_lx":st.local[i]})
    return {"reachable_states":len(parent),**counts,"assert_failure_edges":counts["assert_failure_edges"],
            "lock_accounting_violations":invariant_violations,"shortest_error_witness":witness}


def check(root):
    out={}
    for v in ROOT_DIGEST:
        program=instructions(root/"cases/svcomp26/versions/read_write_lock-2"/v/"program.i",v)
        out[v]={"source_sha256":ROOT_DIGEST[v],"threads":program,**explore(program)}
    assert out["P1"]["assert_failure_edges"] and not out["P2"]["assert_failure_edges"]
    assert not out["P2"]["lock_accounting_violations"]
    return out
