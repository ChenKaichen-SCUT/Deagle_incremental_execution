"""Schema-1 GCC records and supplementary cache eligibility for the candidate frontend."""
import hashlib
import json
import os
import re
import stat
from collections import Counter
from pathlib import Path

PROBES = (('-E', '-', '-o', '-'), ('-E', '-x', 'c++', '-', '-o', '-'))
MARKER = re.compile(rb'(?m)^#\s+\d+\s+"([^"\n]+)"')
VIRTUAL = {'<command-line>', '<built-in>', '<stdin>', '<command line>'}
BUILTIN_LINE = re.compile(rb'(?m)^\s*#\s*(?:line\s+)?\d+\s+"(<(?:built-in-additions|builtin-library(?:-[\w.$]+)?)>)"')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def emit(path, record):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=True) + '\n')


def make_paths(data):
    # GCC -MT gives one fixed target. Decode GCC's make escaping, not shell syntax.
    data = data.replace(b'\\\n', b' ')
    target, sep, values = data.partition(b':')
    if target != b'incdeagle' or not sep:
        raise ValueError('unrecognized_dependency_rule')
    result, token = [], bytearray()
    i = 0
    while i < len(values):
        c = values[i]
        if c == 92 and i + 1 < len(values):
            i += 1
            if values[i] not in b' \t#\\':
                raise ValueError('ambiguous_make_escape')
            token.append(values[i])
        elif c == 36 and values[i+1:i+2] == b'$':
            token.append(c)
            i += 1
        elif c in b' \t\r\n':
            if token:
                result.append(os.fsdecode(bytes(token)))
                token.clear()
        else:
            token.append(c)
        i += 1
    if token:
        result.append(os.fsdecode(bytes(token)))
    if not result:
        raise ValueError('empty_dependency_rule')
    return result


def stamp(path):
    s = path.stat()
    if not stat.S_ISREG(s.st_mode):
        raise ValueError('dependency_not_regular')
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def file_record(cwd, args, raw, rc, depfile):
    """Compute the original seven schema-1 fields while temporary sources still exist."""
    source = (cwd / args[-1]).resolve(strict=True)
    snapshots, paths, markers = {}, {}, {}
    errors = []
    def content(path):
        if path not in snapshots:
            first = stamp(path)
            value = sha(path.read_bytes())
            if stamp(path) != first:
                raise ValueError('dependency_changed_while_reading')
            snapshots[path] = first, value
        return snapshots[path][1]
    unit = 'harness.c' if source == (cwd/'harness.c').resolve() else 'generated/' + content(source)
    generated_labels=set()
    if unit.startswith('generated/'):
        source_bytes=source.read_bytes()
        if 'generated/'+sha(source_bytes)!=unit:
            raise ValueError('generated_source_changed')
        (depfile.parent/'unit-source').write_bytes(source_bytes)
        generated_labels=set(BUILTIN_LINE.findall(source_bytes))
    def identify(spelling):
        if spelling not in paths:
            path = (cwd / spelling).resolve(strict=True)
            name = unit if path == source else (path.name if path.parent == cwd else str(path))
            paths[spelling] = path, name, content(path)
        return paths[spelling]
    def replace(match):
        spelling = os.fsdecode(match[1])
        if spelling in VIRTUAL or match[1] in generated_labels:
            return match[0]
        try:
            _, name, value = identify(spelling)
        except (ValueError, OSError):
            errors.append('unconfirmed_line_marker')
            return match[0]
        markers[name] = value
        return match[0].replace(match[1], os.fsencode(name))
    stable = MARKER.sub(replace, raw)
    evidence = {}
    if rc == 0:
        try:
            for item in make_paths(depfile.read_bytes()):
                _, name, value = identify(item)
                evidence[name] = value
        except (OSError,ValueError):
            errors.append('unconfirmed_compiler_dependency')
        if unit not in evidence or not markers.keys() <= evidence.keys():
            errors.append('line_markers_disagree_with_compiler_dependencies')
    else:
        errors.append('gcc_nonzero')
    if any(stamp(path) != before for path, (before, _) in snapshots.items()):
        errors.append('dependency_changed_during_recording')
    if any((cwd / spelling).resolve(strict=True) != path for spelling,(path,_,_) in paths.items()):
        errors.append('dependency_path_changed_during_recording')
    old = dict(unit=unit, argv=[*args[:-1],unit], raw_argv=args, files=markers, returncode=rc,
               raw_output_sha256=sha(raw), output_sha256=sha(stable))
    return old, dict(kind='file', unit=unit, argv=old['argv'], files=evidence,
                     output_sha256=old['output_sha256'], raw_output_sha256=old['raw_output_sha256'],
                     returncode=rc, errors=sorted(set(errors)))


def probe_record(args, data, raw, rc):
    return dict(kind='probe', argv=args, input_sha256=sha(data), output_sha256=sha(raw),
                returncode=rc, errors=[] if rc==0 else ['gcc_nonzero'])


def flags_supported(args):
    return len(args)>1 and args[0]=='-E' and all(
        a in ('-E','-m32','-m64') or a.startswith('-std=') or
        (len(a)>2 and a[:2] in ('-D','-U','-I')) for a in args[:-1])


def context(directory):
    rows=[json.loads(s) for s in (directory/'frontend-calls.jsonl').read_bytes().splitlines()]
    old=[json.loads(s) for s in (directory/'cpp.jsonl').read_bytes().splitlines()]
    probes=[r for r in rows if r['kind']=='probe']
    files=[r for r in rows if r['kind']=='file']
    errors={err for r in rows for err in r['errors']}
    if sorted(tuple(r['argv']) for r in probes)!=sorted(PROBES):
        errors.add('incomplete_compiler_probe_set')
    if len(old)!=len(files) or not files or len({r['unit'] for r in files})!=len(files):
        errors.add('incomplete_translation_unit_set')
    expected=Counter((tuple(r['raw_argv']),r['raw_output_sha256']) for r in old)
    expected.update((tuple(r['argv']),r['output_sha256']) for r in probes)
    observed=Counter()
    for slot in (directory/'compiler-spool').glob('c.*'):
        if not (slot/'stdout').is_file() or not (slot/'argv').is_file():
            errors.add('incomplete_dispatch_artifact')
            continue
        argv=tuple(os.fsdecode(s) for s in (slot/'argv').read_bytes().split(b'\0')[:-1])
        observed[argv,sha((slot/'stdout').read_bytes())]+=1
        if argv in PROBES and not any(tuple(r['argv'])==argv and r['input_sha256']==sha((slot/'stdin').read_bytes()) for r in probes):
            errors.add('compiler_probe_input_disagreement')
    if expected!=observed:
        errors.add('incomplete_or_modified_preprocessor_stream')
    headers={}
    for row, original in zip(files,old):
        if (any(row[k]!=original[k] for k in ('unit','argv','output_sha256','raw_output_sha256','returncode'))
                or any(row['files'].get(k)!=v for k,v in original['files'].items())):
            errors.add('dependency_record_disagreement')
        for name, digest in row['files'].items():
            if name not in ('program.c','harness.c') and headers.setdefault(name,digest)!=digest:
                errors.add('inconsistent_header_content')
        for name in ('program.c','harness.c'):
            if name in row['files'] and row['files'][name]!=sha((directory/name).read_bytes()):
                errors.add('source_identity_changed')
    if not any(r['unit']=='harness.c' and {'harness.c','program.c'}<=r['files'].keys() for r in files):
        errors.add('missing_project_dependencies')
    identity=json.loads((directory/'compiler-identity.json').read_bytes())
    errors.update(identity.get('errors',[]))
    return dict(schema=2, compiler=identity['identity'], probes=sorted(probes,key=lambda r:r['argv']),
                units=sorted([r['unit'],r['argv'],sorted(r['files'])] for r in files),
                headers=headers, errors=sorted(errors))
