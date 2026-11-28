"""Inspect the sealed full Audit DAG. This reader neither executes inference rules nor calls a solver."""
from array import array
from bisect import bisect_left
from collections import Counter
import mmap
import struct

from d43_project_support import check


class Proof:
    def __init__(self, path):
        self.file = path.open("rb")
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        check(self.data[:12] == b"DEAGD3\x02\x00\x04\x03\x02\x01", "Audit v2 header")
        pos = 12
        self.sections = []
        for width in (16,4,8,16,12,8,12,4,4,4,4,4,20,1):
            n, = struct.unpack_from("<I", self.data, pos)
            self.sections.append((pos+4,n))
            pos += 4+n*width
            check(pos <= len(self.data), "truncated proof section")
        def words(section):
            start,n = self.sections[section]
            return start,n
        self.nodes,self.count = words(0)
        self.literals,_ = words(1)
        self.edges,_ = words(2)
        start,n = words(3)
        self.input_ids = array("I", (self.word(start+16*j) for j in range(n)))
        start,n = words(4)
        self.birth_ids = array("I", (self.word(start+12*j) for j in range(n)))
        self.facts = {}
        start,n = words(12)
        for j in range(n):
            node,op,a,b,c = struct.unpack_from("<IIiii",self.data,start+20*j)
            kind = self.word(self.nodes+16*node+8)
            if kind == 12:
                self.facts[node] = (op,a,b,c)
            else:
                check(kind == 13, "theory record without declaration/inference")
        start,n = words(13)
        self.graph = self.data[start:start+n]

    def word(self,index):
        return struct.unpack_from("<I",self.data,index)[0]

    def clause(self,node):
        start = self.word(self.nodes+16*(node-1))
        end = self.word(self.nodes+16*node)
        return struct.unpack_from(f"<{end-start}i",self.data,self.literals+4*start)

    def exact(self, inputs, facts):
        """Three simultaneous independent conjunctions over the same graph. Bits denote A, B, C, not tag slots."""
        valid = bytearray(self.count)
        occurrence = 0
        prev = 0
        for idx in range(1,self.count):
            end,kind,flags = struct.unpack_from("<III",self.data,self.nodes+16*idx+4)
            if kind in (1,2,3):
                check(self.input_ids[occurrence] == idx, "Audit occurrence alignment")
                mask = inputs[occurrence] if kind == 1 else 0
                occurrence += 1
            elif kind == 12:
                mask = facts[self.facts[idx]]
            elif flags & 7 or kind in (0,7,8,9,11,15):
                mask = 0
            else:
                check(kind in (4,5,6,10,13,14) and end > prev, "unrecognized or parentless proof")
                mask = 7
                for edge in range(prev,end):
                    parent = self.word(self.edges+8*edge)
                    check(parent < idx, "non-topological proof")
                    mask &= valid[parent]
                    if not mask:
                        break
            valid[idx] = mask
            prev = end
        check(occurrence == len(inputs) == len(self.input_ids), "missing input")
        return valid

    def supports(self, node):
        todo = [node]
        seen, leaves, facts = set(), set(), set()
        edges = 0
        while todo:
            idx = todo.pop()
            if idx in seen:
                continue
            seen.add(idx)
            end,kind,flags = struct.unpack_from("<III",self.data,self.nodes+16*idx+4)
            check(not flags & 7, "nonpermanent support in admitted candidate")
            if kind == 1:
                offset = bisect_left(self.input_ids,idx)
                check(self.input_ids[offset] == idx, "missing leaf index")
                leaves.add(offset+1)
            elif kind == 12:
                facts.add(self.facts[idx])
            else:
                start = self.word(self.nodes+16*(idx-1)+4)
                check(start < end, "missing local evidence")
                edges += end-start
                todo.extend(self.word(self.edges+8*j) for j in range(start,end))
        return sorted(leaves),sorted(facts),len(seen),edges

    def close(self):
        self.data.close()
        self.file.close()
