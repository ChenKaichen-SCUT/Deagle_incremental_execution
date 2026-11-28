"""Decode only SI1B shadow files. Stable keys use complete tuples shared by a version pair."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import time

U32=0xffffffff
def signed(x): return x if x<0x80000000 else x-(1<<32)
def check(ok,why):
    if not ok: raise ValueError(why)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def packed(item):
    """The native designator is a sequence of length-prefixed UTF-8 fields."""
    data=item.encode();i=0;out=[]
    while i<len(data):
        sep=data.index(b":",i);length=int(data[i:sep]);start=sep+1;end=start+length
        check(end<=len(data),"designator length");out.append(data[start:end].decode());i=end
    return out

class Registry:
    def __init__(self):
        self.index={};self.rows=[None]
    def key(self,*row):
        got=self.index.get(row)
        if got is None:
            got=len(self.rows);self.index[row]=got;self.rows.append(row)
        return got

class Wire:
    def __init__(self,folder,source):
        start=time.monotonic_ns();seal=json.loads((folder/"seal.json").read_text())
        raw=(folder/"native.bin").read_bytes()
        check(seal["version"]=="SI1B-shadow-1" and hashlib.sha256(raw).hexdigest()==seal["body"] and
              len(raw)==seal["bytes"] and sha(source/"source-catalog.json")==seal["source_sha256"],"catalog integrity")
        self.seal=seal;self.strings=[];self.rows=defaultdict(list);self.metrics=Counter();self.allocated=defaultdict(list)
        offset=0
        def take(n):
            nonlocal offset
            end=offset+n;check(n>=0 and end<=len(raw),"truncated catalog")
            value=raw[offset:end];offset=end;return value
        def word():return struct.unpack("<I",take(4))[0]
        check(take(8)==b"SI1BIN01" and word()==0x01020304,"magic/byte order")
        for i in range(word()):self.strings.append(take(word()).decode())
        check(self.strings and self.strings[0]=="","string sentinel")
        words=word();end=offset+4*words
        check(end+8==len(raw) and raw[end:]==b"SI1END01","invalid word count/footer")
        alloc=hashlib.sha256();cache=hashlib.sha256();self.next_atom=1
        while offset<end:
            tag,n=struct.unpack_from("<II",raw,offset);offset+=8;tag=chr(tag)
            check(tag in "JWEODIXVUTACLRPBKMQqHGFNZYhb","unknown SI1B row")
            check(offset+4*n<=end,"invalid row length")
            vals=struct.unpack_from("<%dI"%n,raw,offset);offset+=4*n
            self.metrics[tag]+=1
            if tag=="N":
                first,width,frame=vals;check(first==self.next_atom,"allocation order")
                if frame:self.allocated[frame].append((first,width))
                self.next_atom+=width;alloc.update(struct.pack("<II",first,width))
            elif tag=="Y":
                domain,hit,op,lo,hi=vals
                cache.update(("%d %d %s %d %d\n"%(domain,hit,self.strings[op],lo,hi)).encode())
            else:self.rows[tag].append(vals)
        z,=self.rows["Z"];self.n=z[0];self.abi=(*z[1:4],self.strings[z[4]],z[5])
        check(self.next_atom==self.n and 0<self.n<1<<30,"final allocation range")
        self.allocation_hash=alloc.hexdigest();self.cache_hash=cache.hexdigest()
        self.read_ns=time.monotonic_ns()-start
    def lit(self,u):
        x=signed(u);check(x in (-1,-2) or 2<=x<2*self.n,"local literal out of bounds");return x

class Model:
    def __init__(self,wire,registry,source,side):
        self.w=wire;self.reg=registry;self.k=registry.key;self.S=wire.strings;self.r=wire.rows
        check(source["version"]=="SI1SRC1" and side in (0,1),"source catalog format")
        self.source=source["sides"][side];self.reasons=Counter()
        # Bind the pre-encoding source plan to the bytes staged for this process.
        check({k:v["sha256"] for k,v in self.source.items()}==wire.seal["inputs"],"staged source differs from lineage")
        self.anchors={(name,int(line)):e["id"] for name,d in self.source.items() for line,e in d["lines"].items()}
        self.shapes={0:0};self.attrs={};self.origins={0:0};self.locations={};self.sites={};self.contexts={0:0}
        self.decls={};self.symbols={};self.events={};self.aliases=defaultdict(set);self.rf_names={}
        self.bind=defaultdict(set);self.interface=defaultdict(set);self.block=defaultdict(set)
        self.layout={};self.members=defaultdict(list);self.layout_memo={};self.safe_memo={}
        self.roots=defaultdict(set);self.expr={};self.template={};self.result={};self.roles=defaultdict(dict)
        self.children=defaultdict(lambda:defaultdict(set));self.bad_child=set();self.root_records=[]
        self.local_classes=defaultdict(set)
        begin=time.monotonic_ns()
        self.source_ir();self.instances();self.producers()
        self.source_ns=time.monotonic_ns()-begin
        begin=time.monotonic_ns()
        self.typed_layouts();self.theory();self.named();self.templates()
        self.catalog_ns=time.monotonic_ns()-begin

    def loc(self,fields):
        file,line,column,fn,anchor=fields;file,fn=self.S[file],self.S[fn]
        if file in self.source:
            check(self.anchors.get((file,line),0)==anchor,"native token lookup differs")
            if anchor:return self.k("token",self.source[file]["file_id"],anchor)
        # Such files originate within the very same native executable; still require a named role/site.
        if (file=="<built-in-additions>" or file.startswith("<builtin-library-")) and line:
            return self.k("native-library",self.w.seal["elf"],file,line,column)
        return 0

    def source_ir(self):
        k=self.k;s=self.S
        for i,tag,count,*parts in self.r["J"]:
            sub=parts[:count];extra=parts[count:]
            check(len(extra)%2==0,"shape arity")
            self.shapes[i]=k("shape",s[tag],tuple(self.shapes[x] for x in sub),
                             tuple((s[x],self.shapes[y]) for x,y in zip(extra[::2],extra[1::2])))
        for i,*parts in self.r["W"]:
            self.attrs[i]=k("attributes",tuple((s[x],self.shapes[y]) for x,y in zip(parts[::2],parts[1::2])))
        defs=defaultdict(set)
        for *lf,name,base,typ,is_type,macro,param in self.r["D"]:
            loc=self.loc(lf)
            if loc and not macro:
                defs[s[name]].add(k("decl",loc,s[lf[3]],s[base],is_type,param))
        self.decls=self.unambiguous(defs,"ambiguous_declaration")
        sourced=set()
        for i,*lf,role,parent in self.r["O"]:
            loc=self.loc(lf);p=self.origins.get(parent,0)
            if parent and not p: self.origins[i]=0;continue
            if not loc:
                # Unlocated generator ancestry is meaningful only inside a finally sourced function/site.
                if s[lf[0]] in self.source or s[lf[0]] and not s[role]=="goto.copy_from":
                    self.origins[i]=0;continue
            self.origins[i]=k("lower",p,loc,s[lf[3]],s[role])
            if loc or parent in sourced:sourced.add(i)
        candidates={};self.site_rows={}
        for *lf,i,origin,fn,operation in self.r["I"]:
            loc=self.loc(lf);der=self.origins.get(origin,0)
            self.site_rows[i]=(s[lf[0]],lf[1],s[fn],s[operation])
            if der and (loc or not s[lf[0]] and origin in sourced):
                candidates[i]=k("site",s[fn],loc,der,s[operation])
        duplicate=Counter(candidates.values())
        self.sites={i:key for i,key in candidates.items() if duplicate[key]==1}
        self.reasons["ambiguous_or_unsourced_sites"]=len(self.r["I"])-len(self.sites)

    def unambiguous(self,by_name,label):
        multi={name:next(iter(v)) for name,v in by_name.items() if len(v)==1}
        cnt=Counter(multi.values())
        out={n:key for n,key in multi.items() if cnt[key]==1}
        self.reasons[label]+=len(by_name)-len(out)
        return out

    def instances(self):
        keys={0:0};parents={};history=[]
        for i,site,spawn,caller,*loops in self.r["X"]:
            spawn,caller=signed(spawn),signed(caller);lp=loops[::2];it=loops[1::2]
            check(len(lp)==len(it),"loop tuple")
            if site in self.sites and spawn in keys and caller in keys and all(j in self.sites for j in lp):
                keys[i]=self.k("occurrence",keys[spawn],keys[caller],tuple((self.sites[j],iteration)
                                 for j,iteration in zip(lp,it)),self.sites[site]);parents[i]=(spawn,caller)
            history.append(i)
        counts=Counter(keys.values())
        for i in history:
            if i in keys and counts[keys[i]]==1 and all(p in self.contexts for p in parents[i]):
                self.contexts[i]=keys[i]
        self.reasons["ambiguous_or_unsourced_contexts"]=len(history)-(len(self.contexts)-1)

    def object_path(self,value,base):
        if not value:return ()
        def path(v):
            f=packed(v);tag,*a=f
            if tag=="symbol":
                return (tag,self.decls[a[0]]) if len(a)==1 and a[0] in self.decls else None
            if tag=="constant":return (tag,*a) if len(a)==2 and a[1] else None
            if tag=="index":children=[path(x) for x in a];return (tag,*children) if all(children) else None
            if tag=="member" and len(a)==2:
                parent=path(a[1]);return (tag,a[0],parent) if parent else None
            return None
        return path(value) if base in self.decls else None

    def producers(self):
        births={(self.S[s],signed(c),self.S[r]) for s,c,r in self.r['b']}
        candidates=defaultdict(set);ev=defaultdict(set);owner_names=defaultdict(set);events_seen=Counter()
        for sym,event,ctx,role,obj,base,typ,glob in self.r["V"]:
            sym,event,role,obj,base=(self.S[x] for x in (sym,event,role,obj,base))
            ctx=signed(ctx);context=self.contexts.get(ctx)
            if ctx==-2 and glob:context=self.k("initial-static")
            if event:events_seen[event]+=1
            if sym and ctx!=-2 and (sym,ctx,role) not in births:
                self.reasons['SSA_BIRTH_UNCONFIRMED']+=1;continue
            if context is None:continue
            objpath=self.object_path(obj,base) if obj else ()
            if objpath is None or not objpath and role not in ("spawn","fence"):continue
            key=self.k("producer",context,role,objpath,self.shapes[typ],glob)
            if sym:
                candidates[sym].add((role,key));owner_names[key].add(sym)
            if event:ev[event].add(key)
        self.events=self.unambiguous(ev,"ambiguous_event")
        for sym,roles in candidates.items():
            valid={(r,k) for r,k in roles if len(owner_names[k])==1}
            self.aliases[sym]={k for _,k in valid}
            for family in (("read","write"),("assign",),("decl",)):
                found={k for r,k in valid if (r.startswith("assign") if family==("assign",) else r in family)}
                if found:
                    if len(found)==1:self.symbols[sym]=next(iter(found))
                    break

    def typed_layouts(self):
        for typ,kind,width in self.r["K"]:self.layout[typ]=(self.S[kind],width)
        for parent,child,name,offset,width,pad in self.r["M"]:
            self.members[parent].append((self.S[name],child,offset,width,pad))
        objs={}
        for nr,name in self.r["q"]:objs[nr]=self.k("reserved-pointer",self.S[name])
        terms={row[0]:row for row in self.r["E"]}
        for nr,term in self.r["Q"]:
            _,op,typ,sym,*_=terms[term]
            name=self.S[sym]
            value=self.symbols.get(name) or self.decls.get(name) if self.S[op]=="symbol" else None
            obj=self.k("address-object",value,self.shapes[typ]) if value else 0
            if nr in objs and objs[nr]!=obj:obj=0
            objs[nr]=obj
        self.universe=0
        if sorted(objs)==list(range(len(objs))) and objs and all(objs.values()) and len(set(objs.values()))==len(objs):
            self.universe=self.k("pointer-universe",tuple(objs[i] for i in range(len(objs))))

    def layout_key(self,typ):
        if typ not in self.layout_memo:
            todo=[typ];seen=set();parts=[]
            while todo:
                t=todo.pop()
                if t in seen:continue
                seen.add(t);links=self.members[t]
                parts.append((self.shapes[t],self.layout.get(t,("unknown",0)),
                              tuple((n,self.shapes[c],off,w,p) for n,c,off,w,p in links)))
                todo.extend(r[1] for r in links)
            self.layout_memo[typ]=self.k("layout",self.w.abi,self.shapes[typ],tuple(sorted(parts)))
        return self.layout_memo[typ]

    def lane(self,typ,bit):
        idx=(typ,bit)
        if idx in self.safe_memo:return self.safe_memo[idx]
        self.safe_memo[idx]=0
        kind,w=self.layout.get(typ,("",0))
        result=0
        if bit<w:
            if kind in ("bool","signedbv","unsignedbv","c_bool"):result=self.k("numeric-bit",kind,bit,w)
            elif kind=="pointer":
                off=w-self.w.abi[1]
                if 0<off<w:
                    if bit<off:result=self.k("byte-offset",bit,off)
                    elif self.universe:result=self.k("object-code-bit",self.universe,bit-off,w-off)
            elif self.w.abi[2]==1:
                links=self.members[typ]
                if kind in ("struct_tag","union_tag") and len(links)==1:result=self.lane(links[0][1],bit)
                elif kind=="array" and len(links)==1 and links[0][3]:
                    _,c,_,ew,_=links[0];sub=self.lane(c,bit%ew)
                    if sub:result=self.k("element-bit",bit//ew,sub)
                elif kind in ("union","struct"):
                    parts=[x for x in links if x[2]<=bit<x[2]+x[3]]
                    if parts and (len(parts)==len(links) if kind=="union" else len(parts)==1):
                        lanes=[]
                        for name,c,off,_,pad in parts:
                            lane=self.lane(c,bit-off)
                            if pad or not lane: break
                            # A union lane is certified only if all active views have a numeric interpretation.
                            if kind=="union" and not self.numeric(c,bit-off):break
                            lanes.append((name,lane))
                        else: result=self.k("storage-bit",kind,tuple(lanes))
        self.safe_memo[idx]=result;return result

    def numeric(self,t,bit):
        kind,w=self.layout.get(t,("",0));links=self.members[t]
        if bit>=w:return False
        if kind in ("bool","signedbv","unsignedbv","c_bool"):return True
        if kind=="pointer":return False
        if kind in ("struct_tag","union_tag"):return len(links)==1 and self.numeric(links[0][1],bit)
        if kind=="array":return len(links)==1 and links[0][3] and self.numeric(links[0][1],bit%links[0][3])
        parts=[x for x in links if x[2]<=bit<x[2]+x[3]]
        return bool(parts) and (len(parts)==len(links) if kind=="union" else len(parts)==1) and all(
            not pad and self.numeric(child,bit-off) for _,child,off,_,pad in parts)

    def theory(self):
        registers=defaultdict(set)
        for sym,w,r in self.r["F"]:registers[(self.S[w],self.S[r])].add(self.S[sym])
        values=defaultdict(set)
        for sym,typ,*lits in self.r["B"]:
            if typ==0 and len(lits)==1:values[self.S[sym]].add(self.w.lit(lits[0]))
        for w,r,raw,ok in self.r["H"]:
            a,b=self.S[w],self.S[r];lit=self.w.lit(raw);names=registers.get((a,b),set())
            key=0
            if ok and a in self.events and b in self.events and len(names)==1 and values[next(iter(names))]=={lit}:
                key=self.k("RF-write-read",self.events[a],self.events[b]);self.rf_names[next(iter(names))]=key
            self.interface_port(key,lit,"RF")
        for e,raw in self.r["G"]:
            event=self.events.get(self.S[e]);lit=self.w.lit(raw)
            self.interface_port(self.k("Guard",event) if event else 0,lit,"Guard")
    def interface_port(self,key,lit,role):
        if lit>=2:
            self.interface[lit//2].add((role,key,lit&1))
            if not key:self.block[lit//2].add("UNCERTIFIED_THEORY_INTERFACE")
        if key:self.bind[key].add(lit)

    def named(self):
        for sym,t,*values in self.r["B"]:
            name=self.S[sym];owners=self.aliases.get(name,set())
            width=len(values);lk=self.layout_key(t) if t else self.k("native-bool")
            for i,raw in enumerate(values):
                lit=self.w.lit(raw)
                lane=self.lane(t,i) if t else self.k("bool-result")
                if not lane and lit>=2:self.block[lit//2].add("LAYOUT_INCOMPATIBLE")
                if lane:
                    for owner in owners:self.bind[self.k("outer",owner,lk,lane,i)].add(lit)

    def templates(self):
        for i,op,t,name,value,attr,*children in self.r["E"]:
            op,name=self.S[op],self.S[name];values=[self.expr[x] for x in children]
            shape=self.shapes[t];leaf=self.rf_names.get(name) or self.symbols.get(name)
            # Anonymous/input-literal operators and opaque pointer/aggregate expressions cannot certify recipes.
            scalar=self.reg.rows[shape][1] in ("bool","signedbv","unsignedbv","c_bool")
            if op in ("symbol","nondet_symbol"):
                array=self.layout.get(t,("",0))[0]=="array" and self.members[t] and self.layout.get(
                    self.members[t][0][1],("",0))[0] in ("unsignedbv","signedbv","c_bool")
                key=self.k("symbol-use",op,shape,leaf,self.layout_key(t) if array else 0) if leaf and (scalar or array) else 0
            elif op=="constant":key=self.k("constant",shape,self.S[value]) if scalar else 0
            elif op in ("not","and","or","xor","nor","nand","implies","=","notequal","if","+","-","*","/",
                        "mod","<","<=",">",">=","typecast","extractbit","extractbits","bitand","bitor","bitxor",
                        "index","shl","lshr","ashr","unary-","unary+","with") and scalar and values and all(values):
                key=self.k("expression",op,shape,self.attrs[attr],tuple(values))
            else:key=0
            self.expr[i]=key
        for i,domain,e in self.r["T"]:self.template[i]=(domain,self.expr[e])
        for i,*lits in self.r["L"]:self.result[i]=tuple(map(self.w.lit,lits))
        pkeys={0:0}
        for i,parent,name,bit,flags in self.r["P"]:pkeys[i]=self.k("recipe-path",pkeys[parent],self.S[name],bit,flags)
        for i,path,name,bit,flags,raw in self.r["R"]:
            role=(pkeys[path],self.S[name],bit,flags)
            self.roles[i].setdefault(role,set()).add(self.w.lit(raw))
        for parent,edge,domain,child in self.r["C"]:
            if edge==U32:self.bad_child.add(child)
            else:self.children[parent][edge,domain].add(child)
        owners={}
        for i,phase,c,kind,assign,lhs in self.r["U"]:
            ctx=self.contexts.get(signed(c));name=self.S[lhs];producer=self.symbols.get(name)
            if ctx and (not name or producer):
                owners[i]=self.k("owner",ctx,self.S[phase],kind,assign,producer or 0)
        for owner,i in self.r["A"]:
            domain,expr=self.template[i]
            if owner in owners and expr:
                key=self.k("conversion-root",owners[owner],domain,expr)
                self.roots[key].add(i)
        # Missing routes get a diagnostic, never a root via a cache address.
        self.reasons["CACHED_INTERNAL_ORIGIN_MISSING"]=len(self.bad_child)
