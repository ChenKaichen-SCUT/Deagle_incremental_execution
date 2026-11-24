"""Complement the native property oracle with executable application-level progress and value checks."""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path
from config import ROOT,TASKS,folder
from oracle import sha,save,read,metadata
from packet import region

COMMON='#define _GNU_SOURCE\n#include <pthread.h>\n#include <stdatomic.h>\n#include <stdlib.h>\n#include <stdio.h>\n'
RW_PRE=r"""
static pthread_mutex_t guard=PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t both;
static _Thread_local int reader_active, sections;
static int overlap,acquired,released;
void assume_abort_if_not(int x){if(!x)abort();}
void reach_error(void){abort();}
void __VERIFIER_atomic_begin(void){pthread_mutex_lock(&guard);}
void __VERIFIER_atomic_end(void){
  pthread_mutex_unlock(&guard);
  if(reader_active && ++sections==5)pthread_barrier_wait(&both);
}
void __VERIFIER_atomic_take_write_lock(void);
void __VERIFIER_atomic_take_read_lock(void);
"""
RW_POST=r"""
void __VERIFIER_atomic_take_write_lock(void){
  pthread_mutex_lock(&guard);take_write_impl();pthread_mutex_unlock(&guard);
}
void __VERIFIER_atomic_take_read_lock(void){
  pthread_mutex_lock(&guard);take_read_impl();acquired++;if(r==2)overlap++;
  pthread_mutex_unlock(&guard);pthread_barrier_wait(&both);
}
static void *tracked_reader(void *arg){
  reader_active=1;reader(arg);pthread_mutex_lock(&guard);released++;pthread_mutex_unlock(&guard);return 0;
}
int main(void){
  pthread_barrier_init(&both,0,2);
  int errors=0,values[]={-8,0,3,17};
  for(int j=0;j<4;j++){
    x=values[j];y=999;r=w=acquired=released=overlap=0;
    pthread_t a,b;pthread_create(&a,0,tracked_reader,0);pthread_create(&b,0,tracked_reader,0);
    pthread_join(a,0);pthread_join(b,0);
    printf("x=%d y=%d remaining=%d acquired=%d completed=%d overlap=%d\n",x,y,r,acquired,released,overlap);
    if(r||w||x!=values[j]||y!=values[j]||acquired!=2||released!=2||!overlap)errors++;
    if(!r){writer(0);if(x!=3||w||r)errors++;}
  }return !!errors;
}
"""
AR_PRE=r"""
static int produced,consumed;
static int instrument_signal(pthread_cond_t *);
#define pthread_cond_signal instrument_signal
"""
AR_POST=r"""
#undef pthread_cond_signal
static int instrument_signal(pthread_cond_t *c){
  if(c==&full)produced++;else if(c==&empty)consumed++;else abort();
  return pthread_cond_signal(c);
}
int main(void){
  pthread_cond_init(&empty,0);pthread_cond_init(&full,0);pthread_mutex_init(&m,0);
  int errors=0;
  for(int j=0;j<12;j++){
    unsigned long start=7*j;num=flag=produced=consumed=0;total=start;pthread_t p,c;
    if(j%2){pthread_create(&c,0,thread2,0);pthread_create(&p,0,thread1,0);}
    else{pthread_create(&p,0,thread1,0);pthread_create(&c,0,thread2,0);}
    pthread_join(p,0);pthread_join(c,0);
    printf("seed=%lu total=%lu produced=%d consumed=%d flag=%d num=%d\n",start,total,produced,consumed,flag,num);
    if(total!=start+3||num!=0||flag!=1||produced!=3||consumed!=3)errors++;
  }return !!errors;
}
"""
UW_PRE=r"""
static int choice,failures,decisions,checks;
int __VERIFIER_nondet_int(void){decisions++;return choice;}
void __VERIFIER_assert(int v){checks++;if(!v)failures++;}
"""
UW_POST=r"""
int main(void){
  int errors=0;int sizes[]={0,1,4,17};
  for(int i=0;i<4;i++)for(choice=0;choice<=1;choice++)for(int before=0;before<=1;before++){
    limit=0;_N=sizes[i];failures=decisions=checks=0;
    if(before)f2(0);
    f1(0);f2(0);
    printf("N=%d choice=%d reader_first=%d limit=%d checks=%d failed=%d\n",_N,choice,before,limit,checks,failures);
    if(limit!=_N||checks!=before+1||failures||decisions!=1)errors++;
  }return !!errors;
}
"""
STACK_POST=r"""
static __attribute__((noreturn)) void finish(int x){
 __asm__ volatile ("int $0x80"::"a"(1),"b"(x):"memory");__builtin_unreachable();
}
void abort(void){finish(89);}
void __assert_fail(const char*a,const char*b,unsigned int c,const char*d){finish(42);}
int __VERIFIER_nondet_int(void){return 17;}
void __VERIFIER_atomic_begin(void){}
void __VERIFIER_atomic_end(void){}
int pthread_mutex_lock(pthread_mutex_t *m){return 0;}
int pthread_mutex_unlock(pthread_mutex_t *m){return 0;}
void _start(void){
 EBStack_init();if(!isEmpty())finish(80);int result=push(17);
 if(result!=1 || isEmpty() || memory[top]!=17 || memory[top+1]!=0)finish(81);
 __VERIFIER_atomic_assert(result);finish(82);
}
"""
def make(task,src):
    if TASKS[task][2]=='primary':
        return src+STACK_POST,['-m32','-ffreestanding','-fno-stack-protector','-fno-pie','-no-pie','-nostdlib','-static','-ffunction-sections','-fdata-sections','-Wl,--gc-sections','-fgnu89-inline'],42
    a,b=region(task,src);fragment=src[a:b]
    if task=='read_write_lock-2':
        for lock in ('read','write'):
            old='void __VERIFIER_atomic_take_'+lock+'_lock()'
            assert fragment.count(old)==1
            fragment=fragment.replace(old,'void take_'+lock+'_impl()')
        # Serialize individual naked C accesses to exercise a concrete legal SC schedule
        # without relying on a host data race. A barrier forces both stale snapshots.
        before,reader=fragment.split('void *reader(',1);output=[];depth=0
        for line in reader.splitlines(keepends=True):
            token=line.strip()
            if token=='__VERIFIER_atomic_begin();':depth+=1
            if token=='__VERIFIER_atomic_end();':depth-=1
            single=re.fullmatch(r'(?:l\s*=\s*x|y\s*=\s*l|int l[xy]\s*=\s*[xy]|l\s*=\s*r\s*-\s*1|r\s*=\s*l|r--|--r|r\s*-=\s*1);',token)
            if depth==0 and single:
                output.extend(['  pthread_mutex_lock(&guard);\n',line,'  pthread_mutex_unlock(&guard);\n'])
                if re.fullmatch(r'l\s*=\s*r\s*-\s*1;',token):output.append('  pthread_barrier_wait(&both);\n')
            else:output.append(line)
        fragment=before+'void *reader('+''.join(output)
        helper='void __VERIFIER_atomic_release_read_lock()'
        if helper in fragment:
            # Deagle treats the entire body of this named primitive atomically.
            fragment='void __VERIFIER_atomic_release_read_lock(void);\n'+fragment.replace(helper,'void release_read_impl()')
            fragment+='\nvoid __VERIFIER_atomic_release_read_lock(void){pthread_mutex_lock(&guard);release_read_impl();pthread_mutex_unlock(&guard);}\n'
        return COMMON+RW_PRE+fragment+RW_POST,['-pthread'],0
    if task=='arithmetic_prog_bad':return COMMON+AR_PRE+fragment+AR_POST,['-pthread'],0
    if task=='unwind1-1':return COMMON+UW_PRE+fragment+UW_POST,['-pthread'],0
    raise ValueError(task)
def run(task,src,dest):
    dest.mkdir(parents=True,exist_ok=False)
    code,flags,expected=make(task,src.read_bytes().decode())
    c=dest/'test.c';c.write_bytes(code.encode())
    with tempfile.TemporaryDirectory() as tmp:
        exe=Path(tmp)/'functional';cmd=['gcc','-std=gnu11','-O0',*flags,str(c),'-o',str(exe)]
        cc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        (dest/'compiler.log').write_bytes(cc.stdout)
        rc=None;stdout=b''
        if not cc.returncode:
            try:
                p=subprocess.run([str(exe)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=8);rc=p.returncode;stdout=p.stdout
            except subprocess.TimeoutExpired as ex:rc=124;stdout=ex.stdout or b''
        (dest/'runtime.log').write_bytes(stdout)
        save(dest/'receipt.json',dict(task=task,input_sha256=sha(src),test_sha256=sha(c),compiler=cmd[:-1]+['<temporary-executable>'],
             compiler_version=subprocess.check_output(['gcc','-dumpfullversion']).decode().strip(),compile_exit=cc.returncode,exit=rc,expected_exit=expected,
             interpretation='legal push reaches original failure' if expected==42 else 'normal completion, values and operation counts',passed=rc==expected))
        print(task,src.name,cc.returncode,rc,expected,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('task');p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    run(a.task,a.source.resolve(),a.output.resolve())
