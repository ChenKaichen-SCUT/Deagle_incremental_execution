"""Production reader for the sealed D43DNS2 stream. All byte counts are bounded by the input."""
from array import array
import json
import struct
import sys

QUERY = 0xffffffff
UNKNOWN = 0xfffffffe
OVERFLOW = 1023
RULES = ("Config", "PO", "APO", "RF", "Guard", "Schema", "SameAddress", "Block")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def group_key(key, domain):
    row = json.loads(key)
    require(isinstance(row, list) and len(row) >= 3 and row[0] == domain and
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) == key, "noncanonical group key")
    if domain == "B":
        require((row[1] == "fallback" and len(row) == 3 and isinstance(row[2], str)) or
                (row[1] == "ssa" and len(row) == 5 and isinstance(row[2], str) and
                 all(type(x) is int for x in row[3:])) or
                (row[1] == "gate" and len(row) == 4 and isinstance(row[2], str) and type(row[3]) is int),
                "Boolean group key schema")
    else:
        require(row[1] in ("fallback", "decl") and row[2] in RULES, "theory group key schema")
        endpoints = 0 if row[1] == "fallback" or row[2] == "Config" else (2 if row[2] in ("PO","APO","RF","SameAddress") else 1)
        require(len(row) == 3+endpoints and all(isinstance(ev,list) and len(ev)==5 and
                (type(ev[0]) is int or ev[0]=="initial") and type(ev[1]) is int and
                all(isinstance(s,str) for s in ev[2:]) for ev in row[3:]), "theory group owners")
    return row


class DenseLibrary:
    def __init__(self, data):
        self.data = memoryview(data)
        self.cursor = 0
        require(self.take(8) == b"D43DNS2\0" and self.unpack("<III") == (0x01020304,1024,OVERFLOW),
                "compact format or capacity")
        self.records = array("Q")
        while True:
            start = self.cursor
            mark = self.take(1)
            if mark == b"D":
                break
            self.records.append(start)
            if mark == b"S":
                ordinal, flags = self.unpack("<IB")
                require(flags < 16 and flags & 12, "invalid scoped disposition")
            else:
                require(mark == b"L", "unknown birth frame")
                ordinal, size, flags = self.unpack("<IIB")
                require(flags < 4 and size > 0, "invalid permanent birth")
                self.take(4*size+256)
            require(ordinal == len(self.records), "discontinuous birth ordinal")
        self.keys, self.slots, self.ops = [], [], []
        for domain in ("B","T"):
            keys, slots, seen = [], [], set()
            for index in range(self.word()):
                slot, length = self.unpack("<HI")
                key = bytes(self.take(length)).decode("utf-8")
                rows = group_key(key, domain)
                require(slot == min(index,OVERFLOW) and key not in seen, "old dense slot or duplicate group")
                keys.append(key)
                slots.append(slot)
                seen.add(key)
                if domain == "T":
                    self.ops.append(RULES.index(rows[2]))
            self.keys.append(keys)
            self.slots.append(slots)
        self.boolean = array("I")
        self.boolean.frombytes(self.take(4*self.word()))
        if sys.byteorder != "little":
            self.boolean.byteswap()
        self.theory = {}
        for i in range(self.word()):
            op,a,b,c,group = self.unpack("<4iI")
            key = (op,a,b,c)
            require(key not in self.theory and group < len(self.ops) and self.ops[group] == op,
                    "invalid theory declaration or group")
            self.theory[key] = (i, group)
        self.used = []
        for count in (len(self.boolean),len(self.theory)):
            length = self.word()
            require(length == (count+7)//8, "UsedLeaf length")
            mask = self.take(length)
            require(not count%8 or not mask[-1] >> (count%8), "UsedLeaf padding")
            self.used.append(mask)
        require(self.word()==len(self.records), "birth directory count")
        self.status=self.word()
        require(self.status in (0,10) and self.take(8)==b"ENDDENSE" and self.cursor==len(self.data),
                "incomplete or trailing archive")

    def take(self, n):
        pos=self.cursor
        require(0 <= n <= len(self.data)-pos, "truncated compact file")
        self.cursor+=n
        return self.data[pos:self.cursor]

    def unpack(self, fmt):
        return struct.unpack(fmt,self.take(struct.calcsize(fmt)))

    def word(self):
        return self.unpack("<I")[0]

    def observed(self, domain, index):
        return bool(self.used[domain][index//8] & (1 << (index%8)))

    def occurrence_flags(self):
        flags=bytearray(len(self.boolean))
        for i,g in enumerate(self.boolean):
            used=self.observed(0,i)
            if g in (QUERY,UNKNOWN):
                require(not used,"nonpermanent UsedLeaf")
                flags[i]=4 if g==QUERY else 8
            else:
                require(g < len(self.keys[0]),"unknown Boolean group")
                flags[i]=int(used) | (2 if self.slots[0][g]==OVERFLOW else 0)
        return flags

    def births(self):
        for i,at in enumerate(self.records,1):
            if self.data[at]==ord("S"):
                yield i,self.data[at+5],None,0,0
                continue
            size,flags=struct.unpack_from("<IB",self.data,at+5)
            begin=at+10
            mid=begin+4*size
            lits=struct.unpack_from("<%di"%size,self.data,begin)
            yield i,flags,lits,int.from_bytes(self.data[mid:mid+128],"little"),int.from_bytes(self.data[mid+128:mid+256],"little")

    def validate_payload(self, nvars, flags):
        # Only a registered, individually observed premise can give a permanent tag its bit.
        known=[0,0]
        for i,entry in enumerate(flags):
            if entry&1:
                known[0] |= 1 << self.slots[0][self.boolean[i]]
        for index,group in self.theory.values():
            if self.observed(1,index):
                known[1] |= 1 << self.slots[1][group]
        for _,family,lits,b,t in self.births():
            if lits is None:
                continue
            require(all(2 <= lit < 2*nvars for lit in lits), "birth literal outside producer model")
            require(family==int(bool(b))+2*int(bool(t)) and not (b & ~known[0] or t & ~known[1]),
                    "tag scope or unobserved slot")
