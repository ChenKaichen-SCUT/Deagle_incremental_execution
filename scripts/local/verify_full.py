"""Compare a complete local 11C reproduction with the frozen solver inputs and results."""
import argparse
import json
import sys
from pathlib import Path

from restore import PROJECT, read

sys.path.insert(0, str(PROJECT / 'scripts/stage11b'))
from bindings import capture_identity
from raw_store import archive


def ranked_answer(raw):
    words = raw.split()
    verdict, variables = map(int, words[:2])
    if verdict == 1 and len(words) == 2:
        return words, {}, []
    pos = 2 + variables
    if verdict != 0 or len(words) <= pos:
        raise ValueError('bad native model')
    count = int(words[pos])
    end = pos + 1 + 2 * count
    ranks = {words[i]: int(words[i+1]) for i in range(pos + 1, end, 2)}
    order = words[end+1:]
    if len(ranks) != count or len(order) != int(words[end]):
        raise ValueError('bad native order export')
    return words[:pos], ranks, order


def equal(left, right, identity):
    if left != right:
        raise ValueError(f'local and frozen records differ at {identity}')


def keyed(rows, keys):
    result = {tuple(row[k] for k in keys): row for row in rows}
    if len(result) != len(rows):
        raise ValueError('duplicate run identity')
    return result


def compare(out):
    ref = PROJECT / 'reports/evidence/stage-11c'
    fields = ('argv', 'source', 'stream', 'graph', 'phases', 'exit', 'properties', 'search_trace')
    def trials(root):
        return keyed(read(root / 'trials.json'), ('case', 'trial', 'mode'))

    frozen, local = trials(ref), trials(out)
    w0, w1 = read(ref / 'witnesses.json'), read(out / 'witnesses.json')
    equal(set(frozen), set(local), 'trial identities')
    sides = 0
    for key, pair in frozen.items():
        equal(len(local[key]['sides']), 2, (key, 'side count'))
        for version, (a, b) in enumerate(zip(pair['sides'], local[key]['sides'])):
            for f in fields:
                equal(a[f], b[f], (key, version, f))
            if 'witness' in a:
                equal(w0[a['witness']], w1[b['witness']], (key, version, 'explicit SC witness'))
            sides += 1

    old, new = read(ref / 'raw/files.json'), read(out / 'raw/files.json')
    suffixes = ('/answer.txt', '/worker/use.tsv', '/approved.tsv', '/worker/search.bin',
                '/plan.txt', '/events.tsv', '/native-contract.tsv')
    paths = {p for p in old if p.startswith('formal/') and p.endswith(suffixes)}
    equal(paths, {p for p in new if p.startswith('formal/') and p.endswith(suffixes)}, 'native artifact paths')
    exact = labels = ties = 0
    scoped = {}
    with archive(ref / 'raw') as baseline, archive(out / 'raw') as local_files:
        for name in sorted(paths):
            if old[name] == new[name]:
                exact += 1
                continue
            a, b = baseline.read(old[name]), local_files.read(new[name])
            if name.endswith('/events.tsv'):
                def labels_by_endpoint(raw):
                    rows = [v.split(b'\t') for v in raw.splitlines()]
                    mapping = dict(rows)
                    equal(len(mapping), len(rows), (name, 'duplicate endpoint'))
                    equal(len(set(mapping.values())), len(rows), (name, 'ambiguous identity'))
                    return mapping
                x, y = labels_by_endpoint(a), labels_by_endpoint(b)
                equal(x.keys(), y.keys(), name)
                # A given old identity must consistently correspond to one current identity in this case.
                table = scoped.setdefault(name.split('/')[1], {})
                for endpoint, old_id in x.items():
                    equal(table.setdefault(old_id, y[endpoint]), y[endpoint], (name, endpoint))
                labels += 1
            elif name.endswith('/answer.txt'):
                v0, r0, o0 = ranked_answer(a)
                v1, r1, o1 = ranked_answer(b)
                equal((v0, r0, sorted(o0)), (v1, r1, sorted(o1)), (name, 'Boolean values and event ranks'))
                equal([r0[e] for e in o0], [r1[e] for e in o1], (name, 'order outside rank ties'))
                ties += 1
            else:
                raise ValueError(f'native file hash differs: {name}')
        for case, table in scoped.items():
            equal(len(table), len(set(table.values())), (case, 'event relabelling bijection'))
        model_docs = 0
        for case in ('fib_updates_8', 'lock12', 'ticket56-reviewed'):
            for side in ('old', 'new'):
                for f in ('goto.json', 'full_model.json', 'visits.json', 'native-bindings.json'):
                    name = f'formal/{case}/1/TC/{side}/{f}'
                    server_cwd = Path('/root/Deagle_incremental_execution/runs/stage-11c-release/work') / case
                    local_cwd = out.parent / 'work' / case
                    equal(capture_identity(f, baseline.read(old[name]), server_cwd),
                          capture_identity(f, local_files.read(new[name]), local_cwd), name)
                    model_docs += 1
    def f0(root):
        rows = keyed(read(root / 'original.json')['rows'], ('case', 'side', 'trial'))
        return {k: [v[f] for f in ('argv', 'source', 'exit', 'properties')] for k, v in rows.items()}
    original_f0 = f0(ref)
    equal(original_f0, f0(out), 'F0 property checks')
    for version, a in read(ref / 'multiquery.json').items():
        b = read(out / 'multiquery.json')[version]
        for f in ('classification', 'stream_sha256', 'properties', 'stream', 'max_address_space', 'timeout_s'):
            equal(a[f], b[f], ('multiquery', version, f))
    return {'version_pairs': len(local), 'version_executions': sides, 'fields': fields,
            'matching_native_artifact_hashes': exact, 'relabelled_event_tables': labels,
            'answer_exports_differing_only_within_equal_ranks': ties, 'canonical_model_documents': model_docs,
            'matching_explicit_sc_witnesses': len(w0), 'f0_comparisons': len(original_f0),
            'matching_multiquery_versions': 2}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    result = compare(args.run / 'export')
    (args.run / 'release-comparison.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))
