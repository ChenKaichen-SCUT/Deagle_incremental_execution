"""Build and run a provenance-only observer at the first native root. Never search or import in the census."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
from pathlib import Path
import re
import shlex
import subprocess

from cases42 import load
from run_stock import BASE, ENV, run, save, sha
from summarize_stock import interpret

BASELINE = "b3803564e0c9badedbdd8ca0ad8acd85a002081f"
ELF = "91a531d0c311f63de4a18f0aca443399ca7c817bfaf3bdcf5a6adfc3c299fc0a"
ROOT = BASE.parent
HEADER = BASE / "stable-identity/si1a_probe.h"


def once(text, before, after):
    if text.count(before) != 1:
        raise ValueError("source anchor count differs: " + before)
    return text.replace(before, after)


def observe(rel, original):
    lines = original.splitlines(keepends=True)
    for i, line in enumerate(lines):
        label = json.dumps(f"{rel}:{i + 1}")
        if rel == "solvers/sat/cnf.cpp":
            line = re.sub(r"(?<!::)\bnew_variable\(\)", f"si1a::one(*this, {label})", line)
        if rel.startswith(("solvers/flattening/", "solvers/prop/")):
            line = line.replace("prop.new_variable()", f"si1a::one(prop, {label})")
            line = line.replace("prop.new_variables(", f"si1a::many(prop, {label}, ")
        lines[i] = line
    text = "".join(lines)
    if rel == "solvers/sat/cnf.cpp":
        for sig, size in [("literalt cnft::new_variable()", "1"),
                          ("bvt cnft::new_variables(std::size_t width)", "width")]:
            anchor = sig + "\n{"
            text = once(text, anchor, anchor + "\n  si1a::alloc(_no_variables, " + size + ");")
    if rel == "goto-symex/symex_target_equation.cpp":
        anchor = "  dense_owner_scope(const char *phase,const symex_targett::sourcet &source)"
        text = once(text, anchor, "  si1a::owner census_owner;\n" + anchor +
                    " : census_owner(phase, source.d1_context)")
    if rel in ("solvers/prop/prop_conv_solver.cpp", "solvers/flattening/boolbv.cpp"):
        bv = "flattening" in rel
        domain = '"BV"' if bv else '"BOOL"'
        signature = ("boolbvt::convert_bv(const exprt &expr, optionalt<std::size_t> expected_width)" if bv
                     else "literalt prop_conv_solvert::convert(const exprt &expr)") + "\n{"
        text = once(text, signature, signature + "\n  si1a::expr current(id2string(expr.id()).c_str());")
        hit = "    // Found in cache\n    return cache_entry;" if bv else "    return cache_entry;"
        text = once(text, hit, '  {\n    si1a::cache("H", ' + domain +
                    ", &cache_entry, 0, 0);\n    return cache_entry;\n  }")
        miss = "  cache_entry = convert_bitvector(expr);" if bv else "  literalt literal = convert_bool(expr);\n\n  // store"
        text = once(text, miss, "  const auto first = prop.no_variables();\n" + miss)
        last = "  cache_entry = convert_bitvector(expr);" if bv else "  cache_entry = literal;"
        text = once(text, last, last + '\n  si1a::cache("M", ' + domain +
                    ", &cache_entry, first, prop.no_variables());")
    if rel == "goto-checker/bmc_util.cpp":
        location = "      const auto &bits = entry.second.literal_map;"
        text = once(text, location, location + "\n      si1a::symbol(id2string(entry.first).c_str(), "
                    "id2string(entry.second.type.id()).c_str(), bits.size());")
    if rel == "solvers/sat/satcheck_minisat2.cpp":
        anchor = "    if(!dependency_manifest::d4_library.empty()) at_root_boundary();"
        text = once(text, anchor, "    si1a::boundary(no_variables());\n" + anchor)
    return ('#include "si1a_probe.h"\n' + text) if text != original else None


def build(native, out, jobs):
    native, out = native.resolve(), out.resolve()
    if sha(native / "src/cbmc/deagle_exe") != ELF:
        raise ValueError("expected frozen D43D/E production binary")
    out.mkdir(parents=True, exist_ok=True)
    production = native / "src"
    files = [*(ROOT / "src/solvers/flattening").glob("*.cpp"), *(ROOT / "src/solvers/prop").glob("*.cpp")]
    files += [ROOT / "src" / f for f in ("solvers/sat/cnf.cpp", "goto-symex/symex_target_equation.cpp",
                                          "goto-checker/bmc_util.cpp", "solvers/sat/satcheck_minisat2.cpp")]
    units = []
    for path in sorted(files):
        rel = path.relative_to(ROOT / "src")
        original = path.read_text()
        instrumented = observe(str(rel), original)
        if instrumented is None:
            continue
        if (production / rel).read_text() != original:
            raise ValueError(f"archived build tree differs at {rel}")
        copy = out / rel
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(instrumented)
        units.append((rel, copy))

    def compile_unit(unit):
        rel, copy = unit
        module = production / rel.parts[0]
        inp = rel.relative_to(rel.parts[0])
        target = inp.with_suffix(".o")
        recipe = subprocess.check_output(["make", "-n", "-W", str(inp), str(target)], cwd=module, text=True)
        cmds = [shlex.split(line) for line in recipe.splitlines() if line.startswith("g++ ") and " -c " in line]
        cmd, = [c for c in cmds if c[-1] == str(inp)]
        obj = copy.with_suffix(".o")
        cmd[cmd.index("-o") + 1:] = [str(obj), str(copy), "-I", str((production / rel).parent), "-I", str(HEADER.parent)]
        subprocess.run(cmd, cwd=module, check=True)
        return dict(file=str(rel), production_sha256=sha(production / rel), observer_sha256=sha(copy),
                    compile=cmd, object=str(obj))

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        receipts = list(pool.map(compile_unit, units))
    cbmc = production / "cbmc"
    recipe = subprocess.check_output(["make", "-n", "-W", "cbmc_parse_options.o", "deagle_exe"],
                                     cwd=cbmc, text=True)
    link, = [shlex.split(line) for line in recipe.splitlines() if line.startswith("g++ ")]
    binary = out / "si1a-deagle"
    link[link.index("-o") + 1] = str(binary)
    # Replace members in private thin archives; preserve frozen group scan order.
    for mod in sorted({Path(r["file"]).parts[0] for r in receipts}):
        archive = production / mod / (mod + ".a")
        members = subprocess.check_output(["ar", "t", str(archive)], text=True).splitlines()
        replacements = {(production / r["file"]).with_suffix(".o"): r["object"]
                        for r in receipts if Path(r["file"]).parts[0] == mod}
        if not set(replacements).issubset({Path(m).resolve() for m in members}):
            raise ValueError("member missing in " + mod)
        private = out / (mod + "-observer.a")
        if private.exists():
            private.unlink()
        subprocess.run(["ar", "crsT", str(private), *[replacements.get(Path(m).resolve(), m) for m in members]],
                       check=True)
        link[link.index("../" + mod + "/" + mod + ".a")] = str(private)
    subprocess.run(link, cwd=production / "cbmc", check=True)
    save(out / "build.json", dict(baseline=BASELINE, production=ELF, observer=sha(binary),
                                  header=sha(HEADER), units=receipts, link=link))


def pack(src, dst):
    # Keep same-run cache equality, never export a process address.
    ids = {}
    with src.open("rb") as inp, dst.open("wb") as raw, gzip.GzipFile(fileobj=raw, filename="", mode="wb", mtime=0) as out:
        for line in inp:
            if line.startswith((b"H\t", b"M\t")):
                fields = line.split(b"\t")
                key = (fields[1], fields[2])
                fields[2] = str(ids.setdefault(key, len(ids) + 1)).encode()
                line = b"\t".join(fields)
            out.write(line)


def model(binary, directory, evidence):
    binary = binary.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    for case, spec in load().items():
        for side in ("P0", "P1"):
            work = directory.resolve() / case / side
            work.mkdir(parents=True, exist_ok=False)
            trace = work / "origin.tsv"
            ENV["DEAGLE_SI1A_TRACE"] = str(trace)
            spec_copy = dict(spec, argv=["--d1-manifest", str(work / "model.tsv"), "--d3-layouts", "--d41-identities", *spec["argv"]])
            run(binary, spec_copy, case, side, work, sha(binary))
            receipt = json.loads((work / "run.json").read_text())
            if receipt["exit_code"] != 77 or receipt["timed_out"]:
                raise RuntimeError(f"model boundary missing: {work}")
            dst = evidence / (case + "-" + side + ".tsv.gz")
            pack(trace, dst)
            save(evidence / (case + "-" + side + ".json"),
                 {**receipt, "trace_sha256": sha(dst), "model_sha256": sha(work / "model.tsv")})


def disabled_control(observer, production, work, evidence):
    # Existing D0 smoke fixture; no additional research case or benchmark arm.
    name = "smoke/worker_violation"
    spec = json.loads((BASE / "bench/manifest.json").read_text())[name]
    if sha(production) != ELF or "DEAGLE_SI1A_TRACE" in ENV:
        raise ValueError("disabled control configuration")
    results = {}
    for kind, binary in (("release", production), ("probe_off", observer)):
        path = work.resolve() / kind
        path.mkdir(parents=True, exist_ok=False)
        cfg = dict(spec, argv=["--d1-manifest", str(path / "model.tsv"), "--d3-layouts",
                               "--d41-identities", *spec["argv"]])
        run(binary.resolve(), cfg, name, "smoke", path, sha(binary))
        meta = json.loads((path / "run.json").read_text())
        parsed, failures = interpret(meta, (path / "stdout").read_text())
        result = {k: parsed[k] for k in ("properties", "classification", "target_status", "unwinding_property_ids",
                  "unwinding_iterations", "unwinding_stop_or_warning", "trace_step_counts")}
        for prop in result["properties"]:
            loc = prop.get("sourceLocation", {})
            if "workingDirectory" in loc:
                if loc["workingDirectory"] != meta["cwd"]:
                    raise ValueError("unexpected property source directory")
                loc["workingDirectory"] = "@WORK@"
        result["search"] = [{k: q[k] for k in ("query", "adapter_message", "reported_variables", "live_clauses",
                             "native_cumulative")} for q in parsed["queries"]]
        results[kind] = dict(binary_sha256=sha(binary), stdout_sha256=meta["stdout_sha256"],
                             exit_code=meta["exit_code"], input_sha256=meta["input_sha256"], result=result)
    if results["release"]["result"] != results["probe_off"]["result"]:
        raise ValueError("disabled observer changed the smoke result")
    save(evidence, results)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    b = sub.add_parser("build")
    b.add_argument("native", type=Path)
    b.add_argument("output", type=Path)
    b.add_argument("--jobs", type=int, default=4)
    m = sub.add_parser("model")
    m.add_argument("binary", type=Path)
    m.add_argument("output", type=Path)
    m.add_argument("evidence", type=Path)
    c = sub.add_parser("off-control")
    for key in ("observer", "production", "work", "evidence"):
        c.add_argument(key, type=Path)
    a = p.parse_args()
    if a.action == "build":
        build(a.native, a.output, a.jobs)
    elif a.action == "model":
        model(a.binary, a.output, a.evidence)
    else:
        disabled_control(a.observer, a.production, a.work, a.evidence)
