"""Independently derive the stage 10 comparisons from native full-model, CDCL and allocator receipts."""
import argparse
import collections
import csv
import gzip
import hashlib
import json
import statistics
import struct
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import digest,file_sha,read
from incdeagle.model.repeat import phase_digest
from scripts.stage7.oracles import retained_projection
from scripts.stage10 import archive
from scripts.stage10.bind import registry,decide
from scripts.stage10.experiment import CASES,PHASES,native_stats,signed_stats
from scripts.stage8.statistics8 import dist

def check(ok,explanation):
    if not ok:raise ValueError(str(explanation))
def save(path,doc):
    path.write_bytes((json.dumps(doc,indent=2,sort_keys=True,ensure_ascii=False,allow_nan=False)+'\n').encode())
def lines(p):
    return [list(map(int,x.split())) for x in p.read_text().splitlines()] if p.is_file() else []
def read_stream(path):
    data=path.read_bytes()
    words=memoryview(data).cast('I')
    i=0;variables=0;clauses=[];goals=None;graph=0
    while i<len(words):
        tag=words[i];i+=1
        check(goals is None,'data follows native solve')
        if tag==0xfffffff1:
            check(words[i]==variables,'var allocation');variables+=1;i+=3
        elif tag==0xfffffff4:i+=2
        elif tag==0xfffffff2:graph+=1
        elif tag in (0xfffffff0,0xfffffff3):
            n=words[i];i+=1;row=tuple(words[i:i+n]);i+=n
            check(len(row)==n and all(x//2<variables for x in row),'unbound CNF literal')
            if tag==0xfffffff0:clauses.append(tuple(sorted(row)))
            else:goals=row
        else:raise ValueError('unknown solver input opcode')
    check(i==len(words) and graph==1 and goals is not None,'incomplete solver request')
    return variables,clauses,goals

_trace={}
def trace(path):
    sha=file_sha(path)
    if sha in _trace:return _trace[sha]
    a=memoryview(path.read_bytes()).cast('i');i=0;dec=0;con=0
    while i<len(a):
        kind,level,n=a[i:i+3];i+=3;check(level>=0,'negative decision level')
        if kind==1:dec+=1;check(n>=0,'bad branch literal')
        elif kind==2:con+=1;i+=n;check(n>=0,'bad conflict')
        else:raise ValueError('unknown CDCL event')
    check(i==len(a),'partial trace')
    _trace[sha]=(sha,dec,con)
    return _trace[sha]

class Audit:
    def __init__(self,root):
        self.root=root
        self.matrix=read(ROOT/'reports/evidence/stage-07/matrix.json')
        self.previous=read(ROOT/'reports/evidence/stage-07/summary.json')
        self.samples={};self.counts=collections.Counter()

    def pair(self,d,c,mode,test):
        metadata=read(d/'complete.json');item=self.matrix[c];files=item['files']
        check(metadata['case']==c and metadata['mode']==mode,'run identity')
        for n in ('phi.json','gamma.json','patch.diff'):check(file_sha(d/n)==files[n],(c,n))
        phi=read(d/'phi.json');gamma=read(d/'gamma.json')
        if test=='timed':
            cfg=read(d.parents[2]/'configuration.json')
            check(cfg['model_reuse']=='off' and not cfg['theory_import'] and cfg['api_calls']==0,'formal solver scope')
        result=[];oldreg=None;oldnative=None;oldraw=None;oldrefs=None
        for phase in ('old','candidate'):
            loc=d/phase;r=read(loc/'receipt.json');command=read(loc/'command.json')
            check(command['argv'][1:]==gamma['source_argv']+gamma['verification_output']+['harness.c'] and
                  command['memory_bytes']==gamma['limits']['memory_bytes']==21474836480 and command['affinity']==list(range(8)), 'actual options and limits')
            check(not any(k.startswith(('INCDEAGLE_S4','INCDEAGLE_S5')) for k in command['environment_keys'])
                  and (('S10_BRIDGE_FD' in command['environment_keys'])==(mode=='S')),'full native route')
            check(not (loc/'native-import.json').exists() and not (loc/'old_done.json').exists(),'historical callback files')
            for n,h in (('harness.c',files['harness.c']),('program.c',files[phase+'/program.c'])):check(file_sha(loc/n)==h,'frozen source')
            status,target=classify((loc/'result.json').read_bytes(),r['exit'],phi)
            check(status==r['verdict'] and status['classification']==('VIOLATION' if phase=='old' or c=='batch_retained' else 'NO_VIOLATION_WITHIN_BOUND'),'target or unwinding')
            if status['classification']=='VIOLATION':
                witness=normalize(target,phi,gamma,{'program.c':files[phase+'/program.c'],'harness.c':files['harness.c']},'result.json',version=phase)
                check(witness==read(loc/'counterexample.json'),'native trace')
                if phase=='candidate':check(retained_projection(c,witness),'original failed assertion interleaving')
                self.counts['witnesses']+=1
            counts={p[0]:list(map(int,p[1:])) for p in (z.split() for z in (loc/'s8-native.tsv').read_text().splitlines())}
            visits=read(loc/'visits.json')
            check(counts['other_dispatch'][0]==len(visits)>0 and all(counts[n][0]>0 for n in ('front','sc','rf','po','ssa_convert'))
                  and all(counts[n][0]==0 for n in ('prefix_dispatch','rebind','prefix_symbols','irep_read','rf_replay')),'full model dispatch/generation')
            models={n:phase_digest(read(loc/(n+'.json'))) for n in PHASES}
            check(models==r['phases'],'structural model')
            if phase=='candidate':check(models==self.previous['diagnostics'][c]['phases'],'independent frozen model')
            path=loc/'worker' if mode=='S' else loc
            n0,n1=native_stats(path/'native-state.tsv')
            check(n0['object']==n1['object'] and n0['pid']==n1['pid'] and n1['level']==0,'native lifecycle')
            metric={z[0]:list(map(int,z[1:])) for z in (s.split() for s in (path/'s8-native.tsv').read_text().splitlines())}
            bound={k:int(v) for k,v in (s.split() for s in (loc/'boundary.tsv').read_text().splitlines())}
            factory=bound['factory_end']-bound['factory_begin']
            times=r['times']
            check(times['model_to_result_ns']==factory+bound['decider_return']-bound['model_ready'] and
                  times['pure_search_ns']==metric['search'][1] and times['pure_search_cpu_ns']==metric['search'][2],'solver-side wall and CDCL scopes')
            ih=file_sha(loc/'s8-input.bin');gh=file_sha(loc/'s8-graph.tsv')
            total,cnf,assumptions=read_stream(loc/'s8-input.bin')
            th,branches,conflicts=trace(path/'search.bin')
            check(conflicts==n1['conflicts']-n0['conflicts'],'complete conflict trace')
            state=r['stats']
            for k in ('starts','decisions','conflicts','propagations','theory_propagations','theory_conflicts'):
                check(state[k]==n1[k]-n0[k],'native search delta '+k)
            row=dict(case=c,mode=mode,phase=phase,classification=status['classification'],unwind=status['unwinding_properties'],
                model_pid=r['model_process'],solver_pid=n0['pid'],object=n0['object'],graph_nodes=n0['graph_nodes'],
                variables=total,input_clauses=len(cnf),allocator_before_clauses=n0['originals'],input_sha256=ih,graph_sha256=gh,
                model=models,full_dispatches=len(visits),sc_calls=counts['sc'][0],search_trace_sha256=th,
                trace_branches=branches,trace_conflicts=conflicts,search_ms=times['pure_search_ns']/1e6,search_cpu_ms=times['pure_search_cpu_ns']/1e6,
                total_ms=times['model_to_result_ns']/1e6,factory_ms=factory/1e6,encode_graph_ms=times['capture_encode_graph_ns']/1e6,
                goal_encode_ms=times['goal_encode_ns']/1e6,bind_ms=times['bind_ns']/1e6,solve_ms=times['solve_ns']/1e6,
                memory_peak_kib=n1['peak_rss_kib'],allocator_bytes=n1['arena_bytes'],postsolve_learnts=n1['learnts'],starts=state['starts'],
                restarts=max(0,state['starts']-1),decisions=state['decisions'],conflicts=state['conflicts'],propagations=state['propagations'],
                theory_propagations=state['theory_propagations'],theory_conflicts=state['theory_conflicts'])
            if mode=='S':
                driver=signed_stats(path/'stats.tsv');check(driver['pid']==n0['pid'] and driver['object']==n0['object'],'address in native driver')
                check(driver['input_variables']==total and driver['input_clauses']==len(cnf),'complete submissions')
                settings=dict(backend='Minisat::ClosureSolver/SC',binary=read(self.root/'final/formal/configuration.json')['native_sha256'],gamma=gamma,phi=phi)
                try:
                    reg=registry(loc,settings)
                except (ValueError,KeyError,OSError,IndexError) as e:reg={'error':str(e)}
                # JSON object member names are strings after a round trip, even for SAT slot numbers.
                check(json.loads(json.dumps(reg))==read(loc/'registry.json'),'signed semantic registry')
                if phase=='candidate':
                    proposal=decide(oldreg,reg,'bad-map' if test=='bad-map' else 'normal') if 'groups' in reg and 'groups' in oldreg else None
                    if proposal:check(digest(proposal)==digest(read(loc/'admission.json')),'re-derived candidate admission')
                    kept=lines(path/'retained.tsv');eligible={a for a,b in (proposal or {}).get('pairs',[]) if a==b}
                    if test=='timed':check(driver['admission']=='keep','timed prototype unexpectedly refused')
                    if driver['admission']=='keep':
                        check(n0['object']==oldnative['object'] and n0['pid']==oldnative['pid'] and driver['generation']==1,
                              'solver object persistence')
                        check(driver['retired_learnts']==oldnative['learnts'] and n0['learnts']==0,'no old learnts')
                        check(kept and len(kept)==driver['actually_reattached'] and len({r[0] for r in kept})==len(kept),'nontrivial native reuse')
                        p0=set(oldraw);p1=set(cnf)
                        for ref,*lits in kept:
                            key=tuple(lits)
                            check(oldrefs.get(ref)==key and key in p0 and key in p1 and all(x//2 in eligible for x in lits),'old Clause allocation, semantics and P1 membership')
                        self.counts['reused_native_clauses']+=len(kept)
                        if test=='timed' and d.parent.name=='01':
                            left,right=collections.Counter(oldraw),collections.Counter(cnf)
                            self.samples[c]=dict(solver_pid=n0['pid'],object_address=n0['object'],
                                model_pids=[result[0]['model_pid'],r['model_process']],old_graph_nodes=driver['old_graph_nodes'],
                                old_roots_retired=driver['old_root_assigns'],old_learnts_retired=driver['retired_learnts'],
                                registry_groups=[len(oldreg['groups']),len(reg['groups'])],same_slot=proposal['confirmed'],
                                different_slot=proposal['renumbered_or_repolarized'],old_live_eligible=len(oldrefs),
                                reused=len(kept),first_cref_and_signed_literals=kept[0],semantic_graph_sha256=reg['graph'],
                                old_only_numeric=sum((left-right).values()),new_only_numeric=sum((right-left).values()),
                                common_numeric=sum((left&right).values()),property=phi,source_options=gamma['source_argv'],
                                old_source_sha256=files['old/program.c'],candidate_source_sha256=files['candidate/program.c'])
                    else:
                        check(driver['generation']==2 and n0['object']!=oldnative['object'] and not kept and driver['actually_reattached']==0,'refusal did not rebuild')
                    check(driver['new_root_assigns_before_input']==driver['new_learnts_before_input']==driver['new_graph_nodes_before_input']==0,'epoch reset')
                else:
                    oldreg,oldnative,oldraw=reg,n1,cnf
                    oldrefs={r[0]:tuple(r[1:]) for r in lines(path/'original-resident.tsv')}
                    sealed=memoryview((path/'learning.bin').read_bytes()).cast('i')
                    i=0;num=0
                    while i<len(sealed):
                        ref,size=sealed[i:i+2];check(ref>=0 and size>0,'invalid native learnt snapshot')
                        i+=2+size;num+=1
                    check(i==len(sealed) and num==n1['learnts'],'incomplete native learning snapshot')
                answer=(loc/'answer.txt').read_text().split()
                code,num=map(int,answer[:2]);check(code==(0 if status['classification']=='VIOLATION' else 1) and num==total,'native answer')
                if code==0:
                    bits=list(map(int,answer[2:2+total]));holds=lambda x:bits[x//2]==(x&1)
                    check(all(any(holds(x) for x in clause) for clause in cnf) and all(holds(x) for x in assumptions),'SAT witness fails full CNF or assumptions')
                row.update(disposition=driver['admission'],retained=driver['actually_reattached'],retired_learnts=driver['retired_learnts'],
                    old_roots=driver['old_root_assigns'],init_switch_ms=driver['init_switch_ns']/1e6,
                    replay_submit_ms=driver['submit_ns']/1e6,read_input_ms=driver['parse_ns']/1e6,seal_ms=driver['retain_ns']/1e6,
                    resident_pss_kib=driver['resident_Pss_kib'],resident_rss_kib=driver['resident_Rss_kib'],seal_payload_bytes=driver['retained_index_bytes'],
                    stable_mapped=reg.get('groups') and len(reg['groups']),admitted_bindings=len((read(loc/'admission.json')).get('pairs',[])))
            else:row.update(disposition='fresh',retained=0)
            result.append(row)
            self.counts['complete_models']+=1
        check(result[0]['model_pid']!=result[1]['model_pid'],'frontend/GOTO/SSA models shared a process')
        if mode=='F':check(result[0]['solver_pid']!=result[1]['solver_pid'],'fresh solver not independent')
        return result

def compare(f,s):
    for a,b in zip(f,s):
        for k in ('model','classification','unwind','input_sha256','graph_sha256','variables','input_clauses','full_dispatches'):
            check(a[k]==b[k],('independent F/S',a['case'],a['phase'],k))

def derive(root,out):
    out.mkdir(parents=True,exist_ok=True)
    obj=Audit(root);base=root/'final';rows=[];summary={}
    for c in CASES:
        cnt=8 if c=='fib_updates_8' else 5
        per=[]
        for i in range(1,cnt+1):
            group={}
            for mode in ('F','S'):
                group[mode]=obj.pair(base/'formal'/c/f'{i:02}'/mode,c,mode,'timed')
                for row in group[mode]:row['repeat']=i;rows.append(row)
            compare(group['F'],group['S'])
            per.append((group['F'],group['S']))
        result={}
        for phase,j in [('old',0),('candidate',1)]:
            stats={}
            for mode,g in [('F',0),('S',1)]:
                series=[r[g][j] for r in per]
                scalar={k for k,v in series[0].items() if type(v) in (int,float) and k not in ('repeat','solver_pid','object','model_pid')}
                stats[mode]={k:dist(r[k] for r in series) for k in sorted(scalar)}
                stats[mode]['trace_hashes']=sorted({r['search_trace_sha256'] for r in series})
            for k in ('search_ms','total_ms','solve_ms','decisions','conflicts','propagations','theory_propagations','theory_conflicts'):
                delta=[r[1][j][k]-r[0][j][k] for r in per]
                stats['S_minus_F_'+k]=dict(values=delta,distribution=dist(delta),faster=sum(x<0 for x in delta))
            result[phase]=stats
        summary[c]=result
    controls={}
    for c,label,reason in [('batch_total','bad-map','refuse_unverified_variable_mapping'),('fib_updates_8','damage-learning','refuse_damaged_learning'),('split_counter','normal','refuse_changed_graph')]:
        d=base/'controls'/(c+'-'+label)
        f=obj.pair(d/'F',c,'F',label);s=obj.pair(d/'S',c,'S',label);compare(f,s)
        check(reason==s[1]['disposition'],label)
        controls[c]=dict(test=label,reason=s[1]['disposition'],candidate=s[1]['classification'],reused=s[1]['retained'])
    controls['assumptions']=(base/'controls/assumptions/controls.tsv').read_text().splitlines()
    check(controls['assumptions']==['guarded\t1 0 1','root\t1 1 0'],'assumption/native root controls')
    controls['unchanged_graph']=(base/'controls/same-graph/unchanged.tsv').read_text().splitlines()
    queries=[list(map(int,row.split())) for row in controls['unchanged_graph'][1:]]
    check(len(queries)==7 and all(row[0]==i and row[2]==row[3] and row[4]==1 for i,row in enumerate(queries))
          and {row[2] for row in queries}=={0,1},'assumptions on unchanged native graph')
    controls['direction']=(base/'controls/same-graph/rf-direction.tsv').read_text().splitlines()
    direction=[r.split('\t') for r in controls['direction']]
    check(len(direction)==2 and all(r[1]=='0' for r in direction) and direction[0][2:4]==direction[1][2:4]
          and direction[0][4].split()==list(reversed(direction[1][4].split())),'stale caller-owned order reproduced')
    save(out/'summary.json',summary);save(out/'trials.json',rows);save(out/'controls.json',controls)
    save(out/'mechanism.json',obj.samples)
    save(out/'verification.json',dict(ordinary_pairs=len(rows)//4,formal_program_solves=len(rows),control_program_solves=12,**obj.counts))
    cols=[k for k in dict.fromkeys(k for r in rows for k in r) if k not in ('model','unwind')]
    with (out/'trials.csv').open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore',lineterminator='\n');writer.writeheader();writer.writerows(rows)
    print('Verified',len(rows),'formal program solves, 12 control program solves,',obj.counts['reused_native_clauses'],'physical original clause reattachments and',obj.counts['witnesses'],'counterexamples.')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path);p.add_argument('--write',type=Path)
    p.add_argument('--evidence',type=Path,default=ROOT/'reports/evidence/stage-10');a=p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        temp=Path(tmp);raw=a.raw or temp/'raw'
        if a.raw is None:archive.unpack(a.evidence,raw)
        dest=a.write or temp/'docs';derive(raw,dest)
        if not a.write:
            for artifact in dest.iterdir():check(file_sha(artifact)==file_sha(a.evidence/artifact.name),'published '+artifact.name)
            print('All six derived outputs match the publication byte-for-byte.')
