"""Build a scratch P0 source-owner observer and check its stream against frozen Audit."""
import argparse
import copy
import hashlib
import os
from pathlib import Path
import shlex
import subprocess

import run_stock
from cases42 import load
from run_d42 import compare
from run_stock import BASE, run, save, sha

PHASES = ("guards", "assignments", "decls", "assumptions", "goto_instructions",
          "function_calls", "io", "constraints")
OBSERVER = r'''
#include "dependency_context.h"
#include <cstdlib>
namespace {
class D43OwnerScope
{
  bool active;
public:
  D43OwnerScope(const char *phase, const symex_targett::sourcet &source)
  {
    static const bool enabled = std::getenv("DEAGLE_D43_OWNER") != nullptr;
    active = enabled && dependency_manifest::stream;
    if(active)
      std::fprintf(dependency_manifest::stream, "OWNER43\t%s\t%d\t%u\n", phase,
                   dependency_manifest::checked_context(source), source.thread_nr);
  }
  ~D43OwnerScope()
  {
    if(active) std::fputs("END43\n", dependency_manifest::stream);
  }
};
}
'''


def make_recipe(directory, source, target):
    output = subprocess.check_output(["make", "-n", "-W", source, target], cwd=directory, text=True)
    commands = [shlex.split(line) for line in output.splitlines() if line.startswith("g++ ")]
    if len(commands) != 1:
        raise ValueError("expected one pinned build recipe")
    return commands[0]


def build(release, scratch):
    scratch.mkdir(parents=True, exist_ok=True)
    if (scratch / "deagle_exe").exists():
        raise FileExistsError(scratch / "deagle_exe")
    sym = release / "src/goto-symex"
    filename = "symex_target_equation.cpp"
    original = (sym / filename).read_bytes()
    if original.decode().splitlines() != (BASE.parent / "src/goto-symex" / filename).read_text().splitlines():
        raise ValueError("translation unit differs from fixed review tree")
    code = original.decode()
    anchor = "for(auto &step : SSA_steps)\n  {"
    for phase in PHASES:
        start = code.index("void symex_target_equationt::convert_" + phase + "(")
        end = code.index("\n}", start)
        body = code[start:end]
        if body.count(anchor) != 1:
            raise ValueError("SSA owner site changed: " + phase)
        code = code[:start] + body.replace(anchor, anchor + '\n    D43OwnerScope d43_owner("' +
                                             phase + '", step.source);') + code[end:]
    edited = scratch / filename
    edited.write_text(OBSERVER + code)
    obj = scratch / "d43_owner.o"
    cmd = make_recipe(sym, filename, "symex_target_equation.o")
    cmd[cmd.index("-o") + 1] = str(obj)
    cmd[cmd.index(filename)] = str(edited)
    cmd.extend(["-I", str(sym)])
    subprocess.run(cmd, cwd=sym, check=True)
    cbmc = release / "src/cbmc"
    native = cbmc / "deagle_exe"
    locked = "3e2622fc86dfe08e632a1f3d54fe337bff8fe589b4985e188b5e7a14a3315bc6"
    if sha(native) != locked:
        raise ValueError("unexpected D4.2 release binary")
    link = make_recipe(cbmc, "cbmc_parse_options.o", "deagle_exe")
    link[link.index("-o") + 1] = str(scratch / "deagle_exe")
    link.insert(link.index("-Wl,--start-group"), str(obj))
    subprocess.run(link, cwd=cbmc, check=True)
    save(scratch / "build.json", dict(source_sha256=hashlib.sha256(original).hexdigest(),
         observer_source_sha256=sha(edited), pinned_release_sha256=locked,
         observer_sha256=sha(scratch/"deagle_exe"), compile=cmd, link=link))


def canonical_site(field, cwd):
    """Re-encode only nested length prefixes containing the run-directory field."""
    if cwd not in field:
        return field
    if field == cwd:
        return b"@WORK@"
    pos = 0
    normalized = bytearray()
    while pos < len(field):
        sep = field.index(b":", pos)
        length = int(field[pos:sep])
        end = sep + 1 + length
        if end > len(field):
            raise ValueError("bad SITE41 length")
        child = canonical_site(field[sep + 1:end], cwd)
        normalized.extend(str(len(child)).encode() + b":" + child)
        pos = end
    return bytes(normalized)


def stream_receipt(path, work):
    digest = hashlib.sha256()
    original = marked = starts = ends = 0
    hints = []
    terms = {}
    with path.open("rb") as stream:
        for line in stream:
            if line.startswith(b"OWNER43\t"):
                starts += 1
            elif line == b"END43\n":
                ends += 1
            else:
                original += len(line)
                if line.startswith(b"TERM\t"):
                    _, index, op, typ, value, *args = line.rstrip(b"\n").split(b"\t")
                    term = b"\t".join([op, typ, value, *(terms[arg] for arg in args)])
                    if index in terms:
                        raise ValueError("duplicate term id")
                    terms[index] = hashlib.sha256(term).hexdigest().encode()
                elif line.startswith((b"H\t", b"VALUE_DEF\t")):
                    kind, name, index = line.rstrip(b"\n").split(b"\t")
                    row = b"\t".join((kind, name, terms[index])) + b"\n"
                    if kind == b"H":
                        hints.append(row)
                    else:
                        digest.update(row)
                elif line.startswith(b"SITE41\t"):
                    tag, site, value = line.rstrip(b"\n").split(b"\t")
                    digest.update(b"\t".join((tag, site, canonical_site(value, os.fsencode(work)))) + b"\n")
                else:
                    digest.update(line)
                continue
            marked += len(line)
    for hint in sorted(hints):
        digest.update(hint)
    for term in sorted(terms.values()):
        digest.update(term)
    if starts != ends:
        raise ValueError("unbalanced observer scopes")
    return dict(canonical_sha256=digest.hexdigest(), original_bytes=original, marker_bytes=marked, scopes=starts)


def probe(binary, d42, out):
    digest = sha(binary)
    for case, spec in load().items():
        gold = d42 / "functional" / case / "1/reference/P0"
        reference = stream_receipt(gold/"native/model.tsv", gold/"work")
        for mode in ("off", "on"):
            directory = out / case / mode
            manifest = directory / "model.tsv"
            opts = copy.deepcopy(spec)
            opts["argv"] = ["--d3-layouts","--d41-identities",
                            "--d1-manifest",str(manifest), *spec["argv"]]
            if mode == "on":
                run_stock.ENV["DEAGLE_D43_OWNER"] = "1"
            else:
                run_stock.ENV.pop("DEAGLE_D43_OWNER", None)
            run(binary, opts, case, "P0", directory, digest)
            receipt = stream_receipt(manifest, directory/"work")
            if receipt["canonical_sha256"] != reference["canonical_sha256"]:
                raise ValueError(f"observer/archived model discrepancy at {directory}")
            receipt["equivalence"] = compare(gold, directory, True)
            save(directory/"observer.json", receipt)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("build","run"))
    p.add_argument("d42", type=Path, help="root containing release/ and functional/")
    p.add_argument("scratch", type=Path)
    a = p.parse_args()
    if a.action == "build":
        build(a.d42.resolve()/"release", a.scratch.resolve()/"observer")
    else:
        probe(a.scratch.resolve()/"observer/deagle_exe", a.d42.resolve(), a.scratch.resolve()/"owners")
