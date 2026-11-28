"""Authenticate one source edit and issue persistent lexical anchors before native encoding."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time
import subprocess
import tempfile

from d42_events import unchanged

TOKEN = re.compile(r"""//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[A-Za-z_$][\w$]*|0[xX][\da-fA-F]+|\d+(?:\.\d+)?|>>=|<<=|==|!=|<=|>=|->|\+\+|--|&&|\|\||[+\-*/&|^%]=|[^\s]""")
NAME = re.compile(r"^[A-Za-z_$][\w$]*$")
ASSIGN = {"=", "+=", "-=", "*=", "/=", "|=", "&=", "^=", "%="}
def digest(data):
    return hashlib.sha256(data).hexdigest()

def tokens(data):
    source=data.decode()
    out=[[] for _ in source.splitlines()]
    i=line=0
    for m in TOKEN.finditer(source):
        line+=source.count("\n",i,m.start())
        s=m.group()
        if not s.startswith(("//","/*")):
            out[line].append(s)
        line+=s.count("\n");i=m.end()
    return out

def compiler_macros(inputs,side,abi):
    # Deagle uses the host C preprocessor. Collect even macros later undefined; ambiguous uses refuse a token.
    names=set();commands=[]
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        for name,pair in inputs.items():(root/name).write_bytes(pair[side])
        for name,pair in inputs.items():
            if not name.endswith(".c") or b"#" not in pair[side]:continue
            cmd=["gcc","-m"+str(abi),"-E","-dD","-x","c",name]
            result=subprocess.run(cmd,cwd=root,capture_output=True,check=True)
            names.update(x.decode() for x in re.findall(rb"^#define\s+([A-Za-z_$][A-Za-z_$0-9]*)",result.stdout,re.M))
            commands.append(cmd)
    return names,commands

def source_pair(inputs, patch_file, directory, abi=64):
    """inputs maps staged logical filename to (P0 bytes,P1 bytes). The patch must cover the changed file."""
    start=time.monotonic_ns()
    directory.mkdir(parents=True,exist_ok=True)
    patch=patch_file.read_bytes() if patch_file else b""
    if sum(x!=y for x,y in inputs.values())>1:
        raise ValueError("SI-1B supports a single changed translation input")
    docs=[{},{}]
    profiles=[compiler_macros(inputs,side,abi) for side in range(2)]
    for file_id,(name,(old,new)) in enumerate(sorted(inputs.items()),1):
        if not name or any(c.isspace() for c in name): raise ValueError("unsupported staging filename")
        linked=unchanged(old,new,patch)
        inv={right:left for left,right in linked.items()}
        sides=[tokens(old),tokens(new)]
        local_macros=[{row[2] for row in lines if len(row)>2 and row[:2]==["#","define"]} for lines in sides]
        changed=[[i+1 for i,row in enumerate(lines) if row and i+1 not in (linked if not side else inv)]
                 for side,lines in enumerate(sides)]
        # Only an isolated replacement of one assignment in a single edit is eligible for outer inheritance.
        rhs={}
        if len(changed[0])==len(changed[1])==1:
            a,b=changed[0][0],changed[1][0]
            def target(row):
                if len(row)>=4 and NAME.fullmatch(row[0]) and row[1] in ASSIGN and row[-1]==";":
                    return row[:2]
            if target(sides[0][a-1]) and target(sides[0][a-1])==target(sides[1][b-1]):
                rhs[b]=a
        previous={}
        for side,lines in enumerate(sides):
            macro_names=local_macros[side] | profiles[side][0]
            base_id=(side<<30)+(file_id<<20)
            next_id=base_id+1; stack=[]; last=[]; records={}; directives=False
            for index,row in enumerate(lines,1):
                if not row:continue
                if row[0]=="#":
                    if len(row)>1 and (row[1]=="line" or row[1].isdigit()): directives=True
                    continue
                old_index=(inv.get(index) or rhs.get(index)) if side else None
                base=previous.get(old_index,{})
                parent=tuple(stack)
                proof="new" if side else "P0"
                # A changed run of adjacent indistinguishable statements is ambiguous.
                adjacent=False
                if side and old_index in linked and len(changed[0])+len(changed[1]):
                    for delta in (-1,1):
                        j=old_index+delta
                        if 1<=j<=len(sides[0]) and j not in linked and sides[0][j-1]==row:
                            adjacent=True
                        j=index+delta
                        if 1<=j<=len(lines) and j not in inv and lines[j-1]==row: adjacent=True
                if directives or any(x in macro_names for x in row):
                    proof="unresolved-source";anchor=0
                elif side and not adjacent and base.get("id") and parent==tuple(base["parent"]) and (
                        base["tokens"]==row or index in rhs):
                    anchor=base["id"];proof="rhs-outer" if index in rhs else "verified-span"
                else:
                    anchor=next_id;next_id+=1
                    if adjacent:proof="ambiguous-copy"
                record=dict(id=anchor,parent=list(parent),tokens=row,proof=proof)
                records[index]=record
                for pos,t in enumerate(row):
                    if t=="}" and stack:stack.pop()
                    elif t=="{":
                        shape=tuple(row[:pos] or last)
                        bid=base.get("opens",{}).get(str(pos)) if side and anchor and anchor==base.get("id") else None
                        if not bid or tuple(bid[1])!=shape or list(stack)!=bid[2]:
                            bid=[next_id,list(shape),list(stack)];next_id+=1
                        record.setdefault("opens",{})[str(pos)]=bid
                        stack.append(bid[0])
                last=row
            docs[side][name]=dict(file_id=file_id,sha256=digest((old,new)[side]),lines=records)
            if next_id>=base_id+(1<<20): raise ValueError("source catalog address space")
            previous=records
    result=dict(version="SI1SRC1",patch_sha256=digest(patch),sides=docs,macro_profiles=[dict(commands=c,names=len(m),sha256=digest("\n".join(sorted(m)).encode())) for m,c in profiles])
    (directory/"source-catalog.json").write_text(json.dumps(result,ensure_ascii=False,separators=(",",":"))+"\n")
    for side,doc in enumerate(docs):
        with (directory/f"P{side}.tokens").open("w") as f:
            print("SI1TOK1",file=f)
            for name,body in doc.items():
                for ln,entry in body["lines"].items():
                    if entry["id"]:print(name,ln,entry["id"],file=f)
    return result,time.monotonic_ns()-start
