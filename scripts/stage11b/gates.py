"""Publication gate for a version/candidate. A rejected answer never becomes a strict result."""
import hashlib,json
from pathlib import Path
from witness import result
def stock_fallback(reference,versions,argv,error):
    records={}
    for side,inputs in zip(('old','new'),versions):
        raw=(reference/side/'receipt.json').read_bytes()
        row=json.loads(raw)
        sources={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in inputs.items()}
        if row['source']!=sources or row['argv']!=argv:
            raise ValueError('no matching independent full run for '+side)
        records[side]=dict(receipt_sha256=hashlib.sha256(raw).hexdigest(),
                           native_exit=row['exit'],properties=row['properties'])
    return dict(path='FULL_REBUILD',basis='independent stock current versions',strict='UNESTABLISHED',
                reason=f'{type(error).__name__}: {error}',versions=records)

def decide(row,independent,witness,strict=False):
    mismatch=[k for k in ('source','argv','phases','stream','graph','exit') if row.get(k)!=independent.get(k)]
    props=lambda r:[(p[0],p[1]) for p in r.get('properties',[])]
    if props(row)!=props(independent):mismatch.append('properties')
    if mismatch:
        return dict(path='FULL_REBUILD',basis='independent stock current version',errors=mismatch,
                    native_exit=independent['exit'],strict='UNESTABLISHED')
    if row.get('closure',{}).get('reason')=='admitted' and row.get('root_check') is None:
        return dict(path='FULL_REBUILD',basis='root oracle missing',native_exit=independent['exit'],strict='UNESTABLISHED')
    cert=witness.get('status')
    if (row.get('exit')==10 or strict) and cert!='EXPLICIT_SC_ORDER':
        return dict(path='FULL_REBUILD',basis='strict completion unavailable',native_exit=independent['exit'],strict='UNESTABLISHED')
    return dict(path='ACCEPT_NATIVE_RESTRICTED',native_exit=row['exit'],
                strict='EXPLICIT_SC_COUNTEREXAMPLE' if cert=='EXPLICIT_SC_ORDER' else 'UNESTABLISHED')
def verify(d,stock):
    row=json.loads((d/'receipt.json').read_bytes());ref=json.loads((stock/'receipt.json').read_bytes())
    witness=result(d) if row['exit']==10 else {'status':'NO_SAT_MODEL'}
    answer=dict(native=decide(row,ref,witness),strict_request=decide(row,ref,witness,True))
    (d/'gate.json').write_text(json.dumps(answer,sort_keys=True,indent=2)+'\n')
    return answer
