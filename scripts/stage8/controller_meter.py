"""Disjoint wall/CPU accounting within one Python process. Child processes are separate."""
from collections import defaultdict
from contextlib import contextmanager
from time import monotonic_ns, process_time_ns


class Recorder:
    def __init__(self):
        self.stack=[]
        self.totals=defaultdict(lambda:[0,0,0,0,0])
        self.phase="old"

    @contextmanager
    def span(self,label):
        frame=[monotonic_ns(), process_time_ns(),0,0]
        self.stack.append(frame)
        phase=self.phase
        try:
            yield
        finally:
            wall=monotonic_ns()-frame[0]
            cpu=process_time_ns()-frame[1]
            self.stack.pop()
            if self.stack:
                self.stack[-1][2]+=wall
                self.stack[-1][3]+=cpu
            row=self.totals[phase+"."+label]
            for i,x in enumerate((1,wall,cpu,wall-frame[2],cpu-frame[3])):
                row[i]+=x

    def hook(self,stack,obj,name,label):
        from unittest.mock import patch
        old=getattr(obj,name)
        def call(*args,**kwargs):
            with self.span(label):
                return old(*args,**kwargs)
        stack.enter_context(patch.object(obj,name,call))
