"""Verify the stage 8 archive, target properties, model comparisons and published tables offline."""
import argparse
import collections
import gzip
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from incdeagle.adapters.deagle import classify
from incdeagle.counterexample import normalize
from incdeagle.model.identity import file_sha, read
from incdeagle.model.repeat import phase_digest
from scripts.stage7.check_evidence import audit_theory, need, restore as restore7
from scripts.stage7.oracles import retained_projection
from scripts.stage8 import archive, statistics8, supplement
from scripts.stage8 import frontend_report,maintenance_report,potential,solver_report,tables

STAGE7 = ROOT/'reports/evidence/stage-07'
EVIDENCE = ROOT/'reports/evidence/stage-08'
PHASES = ('goto', 'raw_ssa', 'sc_input', 'full_model')


def audit(raw, stage7, dest):
    matrix = read(STAGE7/'matrix.json')
    oracle = read(STAGE7/'summary.json')
    plan = read(raw/'formal/plan.json')
    build = read(raw/'build/lock.json')
    environment = read(raw/'audit/environment.json')
    need(environment['originals']['baseline']['commit'] == build['baseline_parent'] and
         environment['originals']['enhanced']['commit'] == build['development_parent'], 'Native base')
    need(environment['project_stage7'] == plan['frozen_project'] == '247894bf77904bb34e547b5a636b8afe8527add4', 'Stage 7 pin')
    expected = {(c, m, i, d) for c in matrix for m in statistics8.MODES for i in range(1, 6) for d in (False, True)}
    need(len(plan['schedule']) == 540 and set(map(tuple, plan['schedule'])) == expected, 'Unbalanced matrix')
    known = {}
    for case, item in matrix.items():
        frozen = stage7/item['case_dir']
        need(all(file_sha(frozen/n) == h for n, h in item['files'].items()), case+' source')
        reference = stage7/'trials'/case/'1'
        known[case] = (read(frozen/'phi.json'), read(frozen/'gamma.json'),
                       read(reference/'old_full/verify/verdict.json'), read(reference/'full/verify/verdict.json'))
        need(file_sha(stage7/'fixed-traces'/(case+'.json')) == environment['frozen'][case]['old_cex_sha256'], case+' CEX0')
    memo = {}
    def model(path):
        key = file_sha(path)
        if key not in memo:
            memo[key] = phase_digest(read(path))
        return memo[key]

    structural = read(raw/'structural/checks.json')
    for case, item in matrix.items():
        # Import optional PyYAML only in the native capture path, not in this audit.
        from scripts.stage8.structural import baseline_projection
        reference = read(stage7/'diagnostics'/case/'full-model/full_model.json')
        full = raw/'structural'/case
        x, y = baseline_projection(read(full/'full_model.json')), baseline_projection(reference)
        row = structural[case]
        need(row['match'] and x == y == row['baseline_digest'] == row['independent_full_digest'], case+' F0 equation')
        p = raw/'side/models'/case/'01/on/F1'
        observed = p/read(p/'complete.json')['attempt']/'full'
        need({k:model(observed/(k+'.json')) for k in PHASES} == oracle['diagnostics'][case]['phases'], case+' F1 model')
    counters = collections.Counter()
    end = 0
    for case, mode, rep, detail in plan['schedule']:
        base = raw/'formal'/case/f'{rep:02}'/('on' if detail else 'off')/mode
        receipt = read(base/'complete.json')
        folder = base/receipt['attempt']
        cfg, m, svc = [read(folder/(f+'.json')) for f in ('settings','measurement','service')]
        phi, gamma, p0, p1 = known[case]
        hashes = matrix[case]['files']
        need(cfg['affinity'] == environment['affinity'] and cfg['limits'] == gamma['limits']
             and cfg['files'] == hashes and cfg['reference_cex0'] == environment['frozen'][case]['old_cex_sha256'], 'Frozen settings')
        need(svc['rc'] == 0 and end <= svc['launch'] < svc['finish'], 'Nonserial or failed service')
        end = svc['finish']
        plain = mode in ('F0','F1')
        old = folder/('old_full' if plain else 'pair/old')
        new = folder/('full' if plain else 'pair/candidate')
        if plain:
            binaries = environment['originals']['baseline']['sha256'] if mode == 'F0' and not detail else build[('baseline' if mode=='F0' else 'development')+'_sha256']
            need(m['binary_sha256'] == binaries, mode+' binary')
            rc = [next(e['rc'] for e in m['processes'] if e['kind']=='wait' and e['role']==role) for role in ('old_full','full')]
        else:
            s = read(folder/'pair/session.json')
            need(s['tool']['development_sha256']==build['development_sha256'] and
                 s['command'][1:]==gamma['source_argv']+gamma['verification_output']+['harness.c'], 'Native session command')
            rc = [s['old_exit'],s['candidate_exit']]
            need({k:model(new/(k+'.json')) for k in PHASES} == receipt['phase_digests'] == oracle['diagnostics'][case]['phases'], case+' candidate model')
            stats = s['native']
            need(stats==m['native'],'Native counters')
            if stats['checkpoint_used']:
                native=read(new/'native-stats.json')
                need(stats=={k:v for k,v in native.items() if k!='executed_dispatches'},'Restored native counters')
                visits=read(stage7/'diagnostics'/case/'full-model/visits.json')
                prefix=read(old/'native-stats.json')['executed_dispatches'][:stats['reused_prefix_symex_steps']]
                need(prefix+native['executed_dispatches']==[{k:v[k] for k in ('thread','function','pc')} for v in visits],'Native execution sequence')
            else:
                need(stats['executed_symex_steps']==len(read(new/'visits.json')),'Full native dispatch count')
            reused = stats['reused_prefix_symex_steps']
            expected_prefix = 0 if mode=='F2' else oracle['cases'][case]['reused_prefix_steps']
            need(reused==expected_prefix and bool(reused)==stats['checkpoint_used'], 'Prefix')
            if not reused:need(bool(m['fallback_reason']), 'Fallback provenance')
            sc = stats.get('sc_counters',{})
            if mode in ('F2','I1'):need(not sc.get('read_bundles_reused',0) and not sc.get('thread_edges_reused',0), 'SC disabled')
            submitted = read(new/'native-import.json')['rows']
            effects = sum(x['effect'] in ('attached','enqueued','contradiction') for x in submitted)
            need(effects == m['theory']['imported'] == (oracle['cases'][case]['lemmas_imported'] if mode=='I3' else 0), 'Solver imports')
            if mode!='I3':need(not submitted,'Withheld plan')
            audit_theory(folder/'pair',hashes)
            counters['certificate_audits']+=1
            counters['verified_incremental_models'] += 1
        for directory, code, role, verdict in zip((old,new),rc,('old','candidate'),(p0,p1)):
            need(file_sha(directory/'program.c') == hashes[role+'/program.c'] and file_sha(directory/'harness.c') == hashes['harness.c'], 'Actual input')
            actual,target = classify((directory/'result.json').read_bytes(),code,phi)
            need(actual == verdict == m['old_verdict' if role=='old' else 'verdict'], 'Bounded property')
            need(file_sha(directory/'result.json') == receipt['old_result_sha256' if role=='old' else 'result_sha256'], 'Raw result')
            if actual['classification']=='VIOLATION':
                trace=read(directory/('cex0.json' if role=='old' else 'cex1.json'))
                need(normalize(target,phi,gamma,{'program.c':hashes[role+'/program.c'],'harness.c':hashes['harness.c']},
                               'result.json',version=role)==trace,'Normalized raw counterexample')
            if role=='candidate' and case in ('partial_counter','batch_retained'):
                need(target['trace'] and trace['property']==phi['id'] and retained_projection(case,trace), 'Retained error witness')
                counters['retained_error_witnesses'] += 1
        counters['detailed' if detail else 'ordinary'] += 1

    for p in sorted((raw/'replay/trials').glob('*/*/receipt.json')):
        row = read(p)
        ref = raw/'replay/captures'/row['input']
        checks = {f:(p.parent/f).read_bytes()==(ref/f).read_bytes() for f in row['checks']}
        need(checks==row['checks'] and (all(checks.values()) and row['status_sat'])==row['exact_search_reproduction'], 'Crossover')
        counters['solver_cross_replays'] += 1
        counters['exact_solver_cross_replays'] += int(row['exact_search_reproduction'])
    for p in sorted((raw/'frontend').glob('*/*/*/receipt.json')):
        row = read(p)
        need(model(p.parent/'frontend/goto.json')==row['goto_digest']==oracle['diagnostics'][row['case']]['phases']['goto'], 'Frontend output')
        counters['frontend_controls'] += 1
    counters['independent_F0_models'] = counters['independent_F1_models'] = len(structural)
    counters['release_old_controls'] = len(list((raw/'old-controls').glob('*/*/receipt.json')))
    for p in sorted((raw/'frontend-setup').glob('*/*/*/receipt.json')):
        r=read(p)
        need(model(p.parent/'frontend/goto.json')==r['goto_digest']==oracle['diagnostics'][r['case']]['phases']['goto'],'Compiler control model')
        counters['gcc_dispatch_controls']+=1
    counters['maintenance_controls'] = len(list((raw/'micro').glob('*/*/changes.json')))
    need(counters['frontend_controls']==125 and counters['gcc_dispatch_controls']==100 and counters['release_old_controls']==15 and counters['maintenance_controls']==45 and
         counters['retained_error_witnesses']==120 and counters['verified_incremental_models']==360, 'Control coverage')
    statistics8.derive(raw/'formal',dest)
    supplement.run(raw,dest)
    tables.render(dest)
    frontend_report.report(raw,dest)
    solver_report.render(dest)
    maintenance_report.render(dest)
    potential.render(dest)
    return dict(counters)


def main(evidence, source=None, stage7=None):
    with tempfile.TemporaryDirectory() as temp:
        tmp=Path(temp)
        if source is None:
            source=tmp/'raw'
            idx=archive.unpack(evidence,source)
        else:
            idx=json.loads(gzip.decompress((evidence/'raw-index.json.gz').read_bytes()))
            for name, expected in idx['files'].items():
                need(archive.valid(name) and file_sha(source/name)==expected,'Archive or run mismatch '+name)
        if stage7 is None:
            stage7=tmp/'stage7'
            stage7.mkdir()
            restore7(STAGE7,stage7)
        dest=tmp/'derived'
        counts=audit(source,stage7,dest)
        for p in sorted(dest.iterdir()):
            need(file_sha(evidence/p.name)==file_sha(p),'Derived table differs '+p.name)
        lock=ROOT/'configs/stage08.lock.json'
        if lock.is_file():
            need(all(file_sha(ROOT/n)==v for n,v in read(lock)['files_sha256'].items()),'Source or published evidence changed')
        print(json.dumps(dict(raw_paths=len(idx['files']),verified_tables=len(list(dest.iterdir())),**counts),sort_keys=True),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence',type=Path,default=EVIDENCE)
    p.add_argument('--source',type=Path,help='verify against an existing measured run')
    p.add_argument('--stage7',type=Path,help='existing restored stage 7 run')
    args=p.parse_args()
    main(args.evidence,args.source,args.stage7)
