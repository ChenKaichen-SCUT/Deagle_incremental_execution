"""Index each native learning occurrence in a representative run without copying proof bodies."""
import collections
import gzip
import json
import sys
import tempfile
from pathlib import Path

from audit import read, save
from theory import parse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'stage11b'))
from raw_store import archive


def cone(nodes, root):
    live = set()
    pending = [root]
    while pending:
        i = pending.pop()
        if i not in live:
            live.add(i)
            pending.extend(nodes[i][2])
    return sorted(live)


def build(evidence):
    index = read(evidence / 'raw/files.json')
    summary = read(evidence / 'summary.json')
    inventory = {}
    examples = {}
    with archive(evidence / 'raw') as store, tempfile.TemporaryDirectory() as work:
        for case in sorted(summary):
            base = 'formal/' + case + '/1/TC/'
            def raw(name):
                return store.read(index[base + name])
            lib = json.loads(gzip.decompress(raw('old/library.json.gz')))
            audit = json.loads(gzip.decompress(raw('new/audit.json.gz')))
            trace = Path(work) / 'trace'
            trace.write_bytes(raw('old/worker/proof.log'))
            _, events, learns, counts = parse(trace)
            skipped = []
            with trace.open() as source:
                for line in source:
                    if line.startswith('X\t'):
                        skipped.append(line.rstrip().split('\t')[1:])
            modes = {}
            for mode in ('T', 'C', 'TC'):
                reps = summary[case]['modes'][mode]['individual']
                sample = reps[0]['reuse']
                assert all(r['reuse']['imports'] == sample['imports'] and
                           r['reuse']['hits'] == sample['hits'] for r in reps)
                modes[mode] = dict(imports=sample['imports'], hits=sample['hits'])
            def action(tag, accepted_modes):
                return {m: dict(native=v['imports'][tag], uses=v['hits'].get(tag, {}))
                        for m, v in modes.items() if m in accepted_modes and tag in v['imports']}
            theories = {}
            for i, item in events.items():
                k = str(i)
                theories[k] = dict(origin=item['origin'], trigger=item['cause'], clause=item['clause'],
                                   p0=lib['theory_decisions'][k], p1=audit['theory_decisions'].get(k),
                                   native=action('t' + k, ('C','TC')))
            cdcl = {}
            proofs = {}
            for i, item in learns.items():
                k = str(i)
                row = dict(signed=item['L'], initial=item['A'][0][1] if item['A'] else None,
                           parents=[p[1] for p in item['A']],
                           p0=lib['mixed_decisions'][k], p1=audit['mixed_decisions'].get(k),
                           native=action('c' + k, ('C','TC')))
                if k in lib['mixed']:
                    spec = lib['mixed'][k]
                    row.update(p0_root=spec['root'], p0_theory=spec['theories'])
                if k in audit['proofs']:
                    proof = audit['proofs'][k]
                    row.update(p1_mode=proof['mode'], p1_theory=proof['used'])
                if row['native']:
                    members = cone(lib['dag'], spec['root'])
                    proofs[k] = dict(old=spec['old_clause'], new=proof['clause'], native=row['native'],
                        p0={j:lib['dag'][j] for j in members},
                        p0_theory={t:dict(origin=lib['theories'][str(t)]['origin'],
                                          trigger=lib['theories'][str(t)]['trigger'],
                                          steps=[n[0] for n in lib['theories'][str(t)]['proof']])
                                   for t in spec['theories']},
                        p1_theory=proof['used'], p1_resolution_steps=len(proof['steps']))
                cdcl[k] = row
            assert len(learns) == counts['all_learnts']
            # In T the native observer does not allocate IDs for preventive reasons.
            # Keep its sequence separate from the interleaved conflict/propagation IDs in C and TC.
            def mode_file(mode, name):
                return json.loads(gzip.decompress(store.read(index[f'formal/{case}/1/{mode}/{name}'])))
            c_lib = mode_file('C', 'old/library.json.gz')
            assert c_lib['capture'] == lib['capture'] and c_lib['mixed'] == lib['mixed']
            t_lib = mode_file('T', 'old/library.json.gz')
            t_audit = mode_file('T', 'new/audit.json.gz')
            t_theory = {k: dict(p0=v, p1=t_audit['theory_decisions'].get(k), native=action('t'+k, ('T',)))
                        for k,v in t_lib['theory_decisions'].items()}
            inventory[case] = dict(first_run=base, trace_sha256=lib['capture'],
                                   proof_library_sha256=audit['library'], native_counts=counts,
                                   skipped_snapshots=skipped, theory=theories, learnt=cdcl,
                                   T_separate_trace=t_lib['capture'], T_theory=t_theory)
            examples[case] = proofs
    save(evidence, 'clause-inventory.json.gz', inventory)
    save(evidence, 'admitted-mixed.json', examples)


if __name__ == '__main__':
    build(Path(sys.argv[1]))
