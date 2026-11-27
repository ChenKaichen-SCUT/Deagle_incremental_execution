"""Identify actual D1 Closure call sites and propagate their opaque descendants in a finished D3 archive."""
import argparse
from array import array
from collections import Counter,defaultdict
import difflib
import gzip
import hashlib
import json
import mmap
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

SITES={
 308:(1,'triplet_initial_guard','solver->assign_literal(~guard_lit, unit_lv);'),
 321:(2,'triplet_initial_rf','solver->assign_literal(~rf_lit, unit_lv);'),
 369:(3,'triplet_after_rf_guard','solver->assign_literal(~guard_lit, unit_lv);'),
 505:(4,'order_self_cycle','conflict_lv = edge.reason;'),
 514:(5,'order_reverse_apo_cycle','conflict_lv = edge.reason;'),
 560:(6,'race_conflict','conflict_lv = conflict_reason;'),
 570:(7,'race_propagation','solver->assign_literal(~race_lit, conflict_reason);'),
 636:(8,'reverse_rf_prevention','solver->assign_literal(~rf_lit_cand, unit_lv);'),
 1034:(9,'triplet_after_guard_rf','solver->assign_literal(~rf_lit, unit_lv);')}
NAMES={j:s for j,s,_ in SITES.values()}

def sha(path,compressed=False):
    h=hashlib.sha256()
    with (gzip.open(path,'rb') if compressed else path.open('rb')) as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()

def save(p,data):p.write_text(json.dumps(data,indent=2)+'\n')

def replace_once(text,anchor,patch):
    if text.count(anchor)!=1: raise ValueError(anchor)
    return text.replace(anchor,patch)

def build(d1,observer,out):
    pin='ed7679588106538c04dcb7dcc504b5ac682f010e'
    assert subprocess.check_output(['git','-C',d1,'rev-parse','HEAD'],text=True).strip()==pin
    assert not subprocess.check_output(['git','-C',d1,'diff','HEAD','--','minisat-2.2.1'])
    base=d1/'minisat-2.2.1/minisat/core/Closure.cc';orig=base.read_text();lines=orig.splitlines(True)
    assert sum(l.count('solver->assign_literal(') for l in lines)==6
    for no,(id_,_,line) in SITES.items():
        assert lines[no-1].strip()==line,(no,lines[no-1])
        # Compound statement keeps the native branch including any unbraced if unchanged.
        indent=lines[no-1][:-len(lines[no-1].lstrip())]
        lines[no-1]=indent+'{ d3_observer_site = '+str(id_)+'; '+line+' }\n'
    closure='extern unsigned d3_observer_site;\n'+''.join(lines)
    old=(observer/'ClosureSolver.cc').read_text()
    marker="""unsigned d3_observer_site=0;
static std::vector<unsigned> d3_accepted_sources;
static void d3_emit_source(char boundary,unsigned source)
{
    static FILE* f=std::fopen("native-origins.tsv","wbx");
    if(!f || !source || source>9) std::abort();
    std::fprintf(f,"%c\\t%u\\n",boundary,source);
}
"""
    solver=replace_once(old,'using namespace Minisat;','using namespace Minisat;\n'+marker)
    solver=replace_once(solver,'    literals_to_assign.push_back(std::make_pair(l, lv));',
        '    d3_accepted_sources.push_back(d3_observer_site);\n    literals_to_assign.push_back(std::make_pair(l, lv));')
    solver=replace_once(solver,'    for(auto p : literals_to_assign)','    size_t source_index=0;\n    if(d3_accepted_sources.size()!=literals_to_assign.size()) std::abort();\n    for(auto p : literals_to_assign)')
    solver=replace_once(solver,"theory_observation('C',minisat_lv);","theory_observation('C',minisat_lv); d3_emit_source('C',d3_observer_site);")
    solver=replace_once(solver,"theory_observation('A',learnt_clause);","theory_observation('A',learnt_clause); d3_emit_source('A',d3_accepted_sources.at(source_index++));")
    assert solver.count('literals_to_assign.clear();')==3
    solver=solver.replace('literals_to_assign.clear();','literals_to_assign.clear(); d3_accepted_sources.clear();')
    texts=[('Closure.cc',orig,closure),('ClosureSolver.cc',old,solver)]
    patches=[]
    for name,pre,post in texts:
        (out/name).write_text(post)
        patches.extend(difflib.unified_diff(pre.splitlines(True),post.splitlines(True),fromfile=name+'.before',tofile=name))
    (out/'probe.patch').write_text(''.join(patches))
    compile0,link0=json.loads((observer/'recipes.json').read_text())
    def reloc(cmd):
        return [str(out/Path(v).name) if Path(v).is_absolute() and Path(v).parent==observer else v for v in cmd]
    comp=reloc(compile0);link=reloc(link0)
    # The reviewed recipes name the D1 observation path outside the checked tree.
    assert str(out/'ClosureSolver.cc') in comp and str(out/'ClosureSolver.o') in link
    comp2=[v.replace(str(out/'ClosureSolver'),str(out/'Closure')) for v in comp]
    link.insert(link.index('-Wl,--start-group'),str(out/'Closure.o'))
    cmds=[comp,comp2,link]
    env=dict(os.environ,PATH='/usr/bin:/bin',LC_ALL='C')
    for i,cmd in enumerate(cmds):subprocess.run(cmd,cwd=d1/('src/solvers' if i<2 else 'src/cbmc'),env=env,check=True)
    save(out/'recipes.json',cmds)
    return dict(d1_implementation=pin,original_closure_sha256=sha(base),official_observer_source_sha256=sha(observer/'ClosureSolver.cc'),
                augmented_binary_sha256=sha(out/'deagle_exe'),sites=SITES,patched_files={name:sha(out/name) for name,_,_ in texts})

def classify(case,p,reference,wd,dest):
    files={}
    for n in ('native-theory.tsv','native-learns.tsv'):
        files[n]=sha(wd/n)
        assert files[n]==sha(reference/(n+'.gz'),True),(case,n)
    stream=(wd/'native-origins.tsv')
    with stream.open('rb') as f,gzip.open(dest/'native-origins.tsv.gz','wb',compresslevel=6) as h:shutil.copyfileobj(f,h)
    files['native-origins.tsv']=sha(stream)
    files['probe_verified_D3_archive']=sha(p)
    counts=defaultdict(Counter);impact=defaultdict(Counter);hist=Counter(); learned=0; unknown=0; dyn=0
    groupcount=Counter()
    triplet=sum(1<<(q-1) for q in (1,2,3,9));rev=1<<7;race=(1<<5)|(1<<6)
    with p.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as a,(wd/'native-theory.tsv').open('rb') as boundary,stream.open('rb') as origins,gzip.open(dest/'learned-origin-masks.tsv.gz','wt') as births,gzip.open(dest/'boundaries.tsv.gz','wt') as out:
        assert a[:8]==b'DEAGD3\x01\x00' and a[-4:]==b'END3'
        sections=[];pos=12
        for width in (16,4,8,16,12,8,12,4,4,4,4,4,20,1):
            n=struct.unpack_from('<I',a,pos)[0];sections.append((pos+4,n));pos+=4+n*width
        assert pos+24+8*18+8==len(a)
        ns,ls,es=sections[0][0],sections[1][0],sections[2][0];nn=sections[0][1]
        eoff,en=sections[12]
        # Only contradiction/PREVENT atoms can support a discharged clause.
        rules={i:o for i,o,_,_,_ in struct.iter_unpack('<IIiii',memoryview(a)[eoff:eoff+en*20]) if o in (16,17)}
        masks=array('H',[0])*nn;initial=array('H',[0])*nn;previous=array('H',[0])*nn
        le=ee=0; ordinal=0
        for i in range(nn):
            hi,end,kind,flags=struct.unpack_from('<4I',a,ns+16*i)
            if kind in (7,8,14):
                row=boundary.readline().split()
                current=origins.readline().split()
                assert len(current)==2 and row and current[0]==row[0]
                if kind==14:
                    par=struct.unpack_from('<I',a,es+8*(end-1))[0]
                    tag=b'C' if rules[par]==16 else b'A'
                else:tag=b'C' if kind==7 else b'A'
                clause=struct.unpack_from('<'+'i'*(hi-le),a,ls+le*4)
                assert row[0]==tag and tuple(map(int,row[1:]))==clause,(case,i)
                k=int(current[1]);assert (k in (4,5,6))==(tag==b'C')
                name=NAMES[k]; category='certified' if kind==14 else 'opaque'
                counts[name][category]+=1;ordinal+=1
                print(ordinal,i,tag.decode(),k,category,sep='\t',file=out)
                if kind!=14: masks[i]=initial[i]=1<<(k-1)
            elif kind in (9,11):
                dyn+=1
            direct=0; prior=0;total=masks[i]
            for off in range(es+ee*8,es+end*8,8):
                par=struct.unpack_from('<I',a,off)[0]
                total|=masks[par];direct|=initial[par];prior|=previous[par]
            masks[i]=total
            if kind==6:
                learned+=1;unknown+=bool(total)
                assert bool(total)==bool(flags&1),(case,i,flags,total)
                hist[str(total)]+=1
                for code,label in NAMES.items():
                    b=1<<(code-1)
                    if total&b:
                        impact[label]['descendants']+=1;impact[label]['direct']+=bool(direct&b)
                        impact[label]['indirect_only']+=not bool(direct&b);impact[label]['via_earlier_learning']+=bool(prior&b)
                if total&triplet:groupcount['triplet_any']+=1
                if total&rev:groupcount['reverse_RF_any']+=1
                if total&race:groupcount['race_any']+=1
                if total&triplet and total&rev:groupcount['triplet_and_reverse_RF']+=1
                print(i,total,direct,prior,sep='\t',file=births)
                prior|=total
            previous[i]=prior
            le,ee=hi,end
        assert not boundary.readline() and not origins.readline() and learned==sections[4][1] and not dyn
    return dict(hashes=files,site_boundaries={label:dict(counts[label]) for label in NAMES.values()},
                by_site_learning={label:dict(impact[label]) for label in NAMES.values()},births=learned,unknown_theory_births=unknown,
                total_boundary_records=ordinal,unknown_mask_histogram=hist,group_descendants=groupcount,dynamic_co_or_opaque_empty=dyn)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for field in ('checked','new_audit'):ap.add_argument(field,type=Path)
    args=ap.parse_args();checked=args.checked.resolve();audit=args.new_audit.resolve()
    # Allow a distributed copy of this script in its output directory.
    audit.mkdir(parents=True,exist_ok=True)
    probe=audit/'probe';probe.mkdir(exist_ok=True);runs=audit/'runs';runs.mkdir(exist_ok=True)
    tree=checked/'final';observer=(checked/'observer').resolve()
    d1=Path.home()/'dependency-reuse/rebuild-d1/final'
    sys.path.insert(0,str(tree/'dependency-reuse/scripts'))
    import run_stock
    from run_d1 import CASES
    run_stock.CPU=2
    info=build(d1,observer,probe)
    cases={};specs=json.loads((run_stock.BASE/'bench/manifest.json').read_text())
    for case in CASES:
        out=runs/case
        run_stock.run(probe/'deagle_exe',specs[case],case,'P0',out,info['augmented_binary_sha256'])
        run=json.loads((out/'run.json').read_text())
        assert not run['timed_out'] and run['exit_code']==10 and run['cpu_affinity']==[2]
        ref=checked/'final-evidence/pairs'/case; dest=audit/case;dest.mkdir()
        cases[case]=classify(case,checked/'final-runs'/case/'mixed-1/proof.bin',ref,out/'work',dest)
    save(audit/'summary.json',dict(d3_source=subprocess.check_output(['git','-C',tree,'rev-parse','HEAD'],text=True).strip(),
        cpu=2,probe=info,cases=cases,mask='bit 1<<(call_site_id-1). Tables contain ProofId, union of opaque ancestors, direct opaque parents, opaque ancestors through earlier CDCL. Distinct per-site descendant counts can overlap.'))
    print(json.dumps({c:(a['births'],a['unknown_theory_births'],a['group_descendants']) for c,a in cases.items()}))
if __name__=='__main__':main()

