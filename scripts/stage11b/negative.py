"""Faults are injected only in private captures. Uncertified paths select the independent stock oracle."""
import json,os,shutil,struct,subprocess,itertools
from pathlib import Path
from bindings import signed_map,write_plan
from trials import check_root
from witness import result
def run_worker(worker,mode,dirs,log):
    r,w=os.pipe()
    with (log/'stdout').open('wb') as out,(log/'stderr').open('wb') as err:
        proc=subprocess.run([worker,mode],input=('\n'.join(map(str,dirs))+'\n').encode(),stdout=out,stderr=err,
              pass_fds=(w,),env=dict(PATH=os.environ['PATH'],LC_ALL='C',S10_PROTOCOL_FD=str(w)),timeout=45)
    os.close(w);protocol=os.read(r,65536).decode();os.close(r)
    return proc.returncode,protocol
def stats(p):
    return dict(l.split('\t') for l in p.read_text().splitlines())
def controls(remote):
    worker=remote/'build/worker';base=remote/'controls/faults';base.mkdir(parents=True,exist_ok=True)
    rows=[]
    def test(name,case,mode,change):
        dest=base/name;dest.mkdir(exist_ok=True);pair=[]
        for side in ('old','new'):
            source=remote/'formal'/case/'1/GS'/side
            d=dest/side;d.mkdir(exist_ok=True);(d/'worker').mkdir(exist_ok=True);pair.append(d)
            for f in ('events.tsv','plan.txt','s8-input.bin','s8-graph.tsv'):shutil.copyfile(source/f,d/f)
        change(pair[1])
        code,protocol=run_worker(worker,mode,pair,dest)
        c=stats(pair[1]/'worker/closure-stats.tsv') if (pair[1]/'worker/closure-stats.tsv').exists() else {}
        s=stats(pair[1]/'worker/stats.tsv') if (pair[1]/'worker/stats.tsv').exists() else {}
        ref=json.loads((remote/'formal'/case/'0/stock/new/receipt.json').read_bytes())
        accepted=(pair[1]/'answer.txt').exists() and code==0
        if accepted:assert int(s['sat_code'])==(0 if ref['exit']==10 else 1)
        rows.append(dict(case=name,worker_exit=code,protocol=protocol,accepted_candidate=accepted,worker_admission=s.get('admission'),graph_reason=c.get('reason'),used=int(c.get('used_derived',0)),originals=int(s.get('actually_reattached',0)),stock_exit=ref['exit']))
        return rows[-1]
    def missing(d):write_plan(d,None,{},'refuse_registry');(d/'events.tsv').unlink()
    def dup(d):
        f=d/'events.tsv';words=[s.split() for s in f.read_text().splitlines()];words[1][1]=words[0][1]
        f.write_text(''.join(k+'\t'+v+'\n' for k,v in words))
        (d/'plan.txt').write_text('refuse_registry\n')
    assert test('missing_events','lock12','GS',missing)['graph_reason']=='unverified_events'
    assert test('duplicate_event_semantics','lock12','GS',dup)['graph_reason']=='unconfirmed_event_bijection'
    def mapfault(d):(d/'plan.txt').write_text('keep\n0 2\n2 2\n')
    assert not test('noninjective_variable_binding','lock12','GS',mapfault)['accepted_candidate']
    assert test('tampered_cdcl','fib_updates_8','damage-learning',lambda d:None)['worker_admission']=='refuse_damaged_learning'
    def corrupt(d):
        f=d/'s8-input.bin';f.write_bytes(f.read_bytes()[:-3])
    assert not test('truncated_assumption_stream','lock12','GS',corrupt)['accepted_candidate']
    # Demonstrate an actual physical cross-slot, polarity-inverting original clause.
    dest=base/'signed-rebind';dest.mkdir(exist_ok=True)
    def encode(rows):return b''.join(struct.pack('<'+'I'*len(r),*r) for r in rows)
    pairs=[]
    for i in range(2):
        d=dest/str(i);d.mkdir(exist_ok=True);(d/'worker').mkdir(exist_ok=True);pairs.append(d)
        var,cl,gr,goal=0xfffffff1,0xfffffff0,0xfffffff2,0xfffffff3
        original=[0,2] if not i else [3,0]
        # P0's (a or b) becomes (~new_b or new_a). The assumptions also change.
        (d/'s8-input.bin').write_bytes(encode([(var,0,2,1),(var,1,2,1),(cl,2,*original),(gr,),(goal,1,0 if not i else 1)]))
        (d/'s8-graph.tsv').write_text('');write_plan(d,{},({0:0,1:2} if not i else {0:3,1:0}),'old' if not i else 'keep')
    rc,log=run_worker(worker,'GS',pairs,dest);st=stats(pairs[1]/'worker/stats.tsv')
    assert rc==0 and int(st['actually_reattached'])==1 and int(st['sat_code'])==0
    rows.append(dict(case='signed_slot_swap',mapping={'0':3,'1':0},originals=1,protocol=log,verified_p1_original_and_current_assumption=True))
    dest=base/'root-unsat-withdrawal';dest.mkdir(exist_ok=True);dirs=[]
    for i in range(2):
        d=dest/str(i);d.mkdir(exist_ok=True);(d/'worker').mkdir(exist_ok=True);dirs.append(d)
        program=[(var,0,2,1),(cl,1,1)]
        if not i:program.append((cl,1,0))
        (d/'s8-input.bin').write_bytes(encode(program+[(gr,),(goal,0)]))
        (d/'s8-graph.tsv').write_text('');write_plan(d,{}, {0:0},'old' if not i else 'keep')
    rc,log=run_worker(worker,'GS',dirs,dest)
    prior,after=[stats(d/'worker/stats.tsv') for d in dirs]
    assert rc==0 and prior['sat_code']=='1' and after['sat_code']=='0' and prior['object']==after['object']
    rows.append(dict(case='withdraw_unit_after_root_UNSAT',same_object=True,sat_codes=[1,0],protocol=log))
    # Remove a supported order in a copy of the candidate output. The independent oracle must catch it.
    dest=base/'missing-derived-order';dest.mkdir(exist_ok=True);(dest/'worker').mkdir(exist_ok=True)
    source=remote/'formal/lock12/1/GS/new'
    shutil.copyfile(source/'native-bindings.json',dest/'native-bindings.json')
    names=dict(line.split() for line in (source/'events.tsv').read_text().splitlines())
    facts=(source/'worker/closure.tsv').read_text().splitlines()
    missing=next(x for x in facts if x.endswith('\t0\t1'));facts.remove(missing)
    (dest/'worker/closure.tsv').write_text('\n'.join(facts)+'\n')
    try:check_root(dest,names)
    except ValueError as ex:rows.append(dict(case='missing_retained_order',verdict='FULL_REBUILD',reason=str(ex)))
    else:raise RuntimeError('incomplete closure passed independent oracle')
    unsat=(source/'answer.txt').read_text().split()
    assert len(unsat)==2 and unsat[0]=='1'
    rows.append(dict(case='new_UNSAT_after_old_SAT',stale_ranks_exported=0,answer_header=unsat))
    (base/'negative.json').write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':
    import sys
    controls(Path(sys.argv[1]).resolve())
