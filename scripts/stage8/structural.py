"""Check full equations, allowing only certified independent assignments at thread creation."""
import shutil
import re
import sys
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.model.identity import file_sha,read,save
from incdeagle.model.repeat import phase_digest

TLS={'__CPROVER_rounding_mode','__CPROVER_thread_id','__CPROVER_thread_key_dtors'}
LOCALS={'pthread_create::'+s for s in ('thread','arg','attr','start_routine','1::this_thread_id','1::next_thread_key')}

def baseline_projection(doc,*,frame_copies=True,certificate=None):
    # 'visit' and 'oc_name' are annotations introduced after F0.
    # Retain every equation row, argument, guard, type, source coordinate,
    # relationship and its sign. Distinct SSA definitions commute only after
    # checking their equations and all operand / guard dependencies.
    s=[{k:v for k,v in row.items() if k not in ('visit','oc_name')} for row in doc['steps']]
    pool=doc['ireps']
    @lru_cache(None)
    def symbols(index):
        if index is None:return frozenset()
        node=pool[index]
        found=set()
        if node['id'] in ('side_effect','nondet_symbol','dereference'):
            raise ValueError('Impure operand in a spawn-local equation')
        if node['id']=='symbol':
            found.add(pool[node['named']['identifier']]['id'])
        for child in [*node.get('sub',[]),*(v for k,v in node.get('named',{}).items() if k not in ('#source_location','#end_location'))]:
            found.update(symbols(child))
        return frozenset(found)
    spawn={(r['thread'],r['function'],r['pc'],r['local_source_group'],r['guard']) for r in s if r['kind']=='spawn'}
    def key(row):
        if (row.get('kind')!='assignment' or not row.get('hidden')
                or row.get('function')!='pthread_create' or row.get('rhs') is None):
            return None
        place=(row['thread'],row['function'],row['pc'],row['local_source_group'],row['guard'])
        if place not in spawn:return None
        lhs=pool[row['lhs']]
        condition=pool[row['condition']]
        if (lhs['id']!='symbol' or pool[lhs['named']['identifier']]['id']!=row.get('local_symbol') or
                condition['id']!='=' or condition.get('sub')!=[row['lhs'],row['rhs']]):return None
        if frame_copies and row.get('object') in LOCALS and re.fullmatch(re.escape(row['object'])+r'!\d+@0#1',row['local_symbol']):
            return ('frame',*place)
        if row.get('object') not in TLS:return None
        if not re.fullmatch(re.escape(row['object'])+r'!\d+#1',row.get('local_symbol','')):return None
        rhs=pool[row['rhs']]
        def literal(item,value):
            return (item['id']=='constant' and not item.get('sub') and 'value' in item.get('named',{})
                    and pool[item['named']['value']]['id']==value)
        if row['object']=='__CPROVER_thread_key_dtors':
            if rhs['id']!='array_of' or len(rhs.get('sub',[]))!=1 or not literal(pool[rhs['sub'][0]],'NULL'):return None
        elif not literal(rhs,'0'):return None
        return ('tls',*place)
    i=0
    while i<len(s):
        k=key(s[i])
        if k is None:i+=1;continue
        j=i+1
        while j<len(s) and key(s[j])==k:j+=1
        block=s[i:j]
        defined={r['local_symbol'] for r in block}
        if len(defined)!=len(block) or any(defined & (symbols(r['rhs'])|symbols(r['guard'])) for r in block):
            raise ValueError('Dependent spawn-local definitions')
        if certificate is not None and len(block)>1:
            certificate.append({'family':k[0],'first_row':i,'rows':len(block),'original_order':[r['local_symbol'] for r in block],
                                'operand_or_guard_reads_of_block_targets':[]})
        s[i:j]=sorted(block,key=lambda r:r['local_symbol'])
        i=j
    return phase_digest({**doc,'steps':s})


def capture(source,binary,out):
    from incdeagle.comparison import bounded
    from scripts.stage2.check_case import load_case
    from scripts.stage7.inputs import validate
    matrix=read(ROOT/'reports/evidence/stage-07/matrix.json')
    out.mkdir(parents=True,exist_ok=True)
    results={}
    for name,item in matrix.items():
        case=validate(source,item)
        _,gamma,phi=load_case(case)
        d=out/name;d.mkdir(exist_ok=True)
        if not (d/'receipt.json').is_file():
            for a,b in [('candidate/program.c','program.c'),('harness.c','harness.c')]:shutil.copyfile(case/a,d/b)
            command=[binary,*gamma['source_argv'],*gamma['verification_output'],'harness.c']
            service=bounded(command,d,d,gamma['limits'],env={'S8_MODEL_OUT':d,'INCDEAGLE_JSON_OUTPUT':d/'result.json'})
            verdict,target=classify((d/'result.json').read_bytes(),service['exit_code'],phi)
            assert verdict==read(source/'trials'/name/'1/full/verify/verdict.json')
            orig=read(d/'full_model.json')
            ref=read(source/'diagnostics'/name/'full-model/full_model.json')
            x,y=baseline_projection(orig),baseline_projection(ref)
            save(d/'receipt.json',{'binary':file_sha(binary),'old_release':'a159f9923722646185ba8028610b2eef2618fa72',
                'source':file_sha(d/'program.c'),'baseline_digest':x,'independent_full_digest':y,'match':x==y,'verdict':verdict})
        record=read(d/'receipt.json')
        orig=read(d/'full_model.json')
        ref=read(source/'diagnostics'/name/'full-model/full_model.json')
        left=[];right=[]
        strict_left=baseline_projection(orig,frame_copies=False)
        strict_right=baseline_projection(ref,frame_copies=False)
        x=baseline_projection(orig,certificate=left)
        y=baseline_projection(ref,certificate=right)
        results[name]={**record,'baseline_digest':x,'independent_full_digest':y,'match':x==y,
                       'tls_only_match':strict_left==strict_right,'tls_only_digests':[strict_left,strict_right],
                       'baseline_groups':left,'reference_groups':right}
        save(d/'commutation.json',results[name])
        print('Standalone full model',name,results[name]['match'],flush=True)
    save(out/'checks.json',results)
    if not all(r['match'] for r in results.values()):raise ValueError('Investigate full model mismatch')


if __name__=='__main__':capture(*map(lambda s:Path(s).resolve(),sys.argv[1:]))
