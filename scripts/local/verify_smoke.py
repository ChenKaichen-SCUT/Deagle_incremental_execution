"""Compare a local stock/F/TC run to the frozen six program inputs and native use records."""
import argparse
import json
from pathlib import Path

from restore import PROJECT, read, sha


def check(run):
    evidence = PROJECT / 'reports/evidence/stage-11c'
    trials = {(r['case'], r['trial'], r['mode']): r for r in read(evidence / 'trials.json')}
    objects = read(evidence / 'raw/files.json')
    rows = []
    for case in ('fib_updates_8', 'lock12', 'ticket56-reviewed'):
        for mode in ('stock', 'F', 'TC'):
            trial = 0 if mode == 'stock' else 1
            prefix = Path('formal', case, str(trial), mode)
            recorded = trials[case, trial, mode]
            row = dict(case=case, mode=mode, sides=[])
            for side, expected in zip(('old', 'new'), recorded['sides']):
                work = run / prefix / side
                actual = read(work / 'receipt.json')
                for key in ('argv', 'source', 'properties', 'exit', 'stream', 'graph', 'search_trace'):
                    if actual[key] != expected[key]:
                        raise ValueError(f'{prefix}/{side}: different {key}')
                result = {k: actual[k] for k in ('exit', 'properties', 'stream', 'graph', 'search_trace')}
                if mode == 'TC' and side == 'new':
                    for name in ('approved.tsv', 'worker/use.tsv'):
                        h = sha(work / name)
                        if h != objects[(prefix / side / name).as_posix()]:
                            raise ValueError(f'{prefix}/{side}: different {name}')
                        result[name] = h
                    uses = [line.split('\t') for line in (work / 'worker/use.tsv').read_text().splitlines()]
                    result['mixed_import_ids'] = sorted({r[1] for r in uses if r[0] == 'import' and r[1].startswith('c')})
                    result['mixed_hit_ids'] = sorted({r[1] for r in uses if r[0] == 'hit' and r[1].startswith('c')})
                row['sides'].append(result)
            rows.append(row)
    return {'frozen_project': '7d2d08ecbf6e643d3537131489ab6ba23c327c52', 'pairs': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    path = args.run / 'smoke-check.json'
    path.write_text(json.dumps(check(args.run), indent=2, sort_keys=True) + '\n')
    print('Verified 18 local program executions against the frozen release:', path)
