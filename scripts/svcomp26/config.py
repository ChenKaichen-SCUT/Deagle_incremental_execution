"""Frozen P0 panel; bounds are fixed per task before looking at repair attempts."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TAG='7efe28dd29576b46927b7a34e8f742bd90966a75'
DEAGLE='b84a95d9d02e9fc48217373bf71564db1cb8ce4029644936a893aaaaef0a529e'
WORKER='c474a95f9d668619bdc138382bd59b1f070190c8197fa91071f9aca49075c204'
TASKS={
 'read_write_lock-2':('pthread-atomic',4,'named-short'),
 'arithmetic_prog_bad':('pthread-deagle',5,'secondary'),
 'stack-2':('pthread',7,'short-functional-control'),
 'unwind1-1':('pthread-theta',4,'secondary-simple-bound'),
 '25_stack_longer-1':('pthread-ext',3,'primary'),
 '25_stack_longest-2':('pthread-ext',3,'primary'),
 '26_stack_cas_longer-1':('pthread-ext',3,'primary'),
 'bounded_buffer':('pthread-complex',6,'named-official-oom'),
 'elimination_backoff_stack':('pthread-complex',5,'named-official-oom'),
 'safestack_relacy':('pthread-complex',5,'named-official-unknown'),
 'workstealqueue_mutex-1':('pthread-complex',8,'different-property')}
def folder(name):return ROOT/'cases/svcomp26/c'/TASKS[name][0]
