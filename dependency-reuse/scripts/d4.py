"""Record one P0 or verify one rebuilt P1 with the native first-boundary D4 path."""
import argparse
from pathlib import Path
import subprocess
import sys

from d4_prepare import SCHEMA, RULES, TOOL_FILES, check_library, digest, save


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("record","record-cold","reuse"))
    parser.add_argument("--binary",required=True,type=Path)
    parser.add_argument("--tools",required=True,type=Path)
    parser.add_argument("--out",required=True,type=Path,help="new output directory")
    parser.add_argument("--library",type=Path,help="completed P0 record directory")
    parser.add_argument("--source",action="append",type=Path,default=[],
                        help="additional input or included source to identify in the P0 receipt")
    try:
        separator=sys.argv.index("--")
    except ValueError:
        parser.error("put the complete original verifier arguments after --")
    args=parser.parse_args(sys.argv[1:separator])
    verifier_args=sys.argv[separator+1:]
    if not verifier_args or any(v.startswith(("--d1-","--d2-","--d3-","--d4-")) for v in verifier_args):
        parser.error("expected original verification arguments")
    if (args.mode=="record") != (args.library is None):
        parser.error("supply --library only when loading a P0")
    binary,tools,out=(p.resolve() for p in (args.binary,args.tools,args.out))
    files={str(p.resolve()):digest(p) for p in [*args.source,*(Path(v) for v in verifier_args if Path(v).is_file())]}
    if not files:parser.error("identify at least one program input")
    out.mkdir(parents=True,exist_ok=False)
    if args.mode=="record":
        flags=["--d3-layouts","--d1-manifest",out/"model.tsv","--d3-proof",out/"proof.bin"]
    else:
        lib=args.library.resolve()
        check_library(lib,binary,tools)
        flags=["--d4-load",lib,"--d4-mode",args.mode,"--d4-out",out,"--d4-tools",tools]
    command=[binary,*flags,"--d4-search-log",out/"search.tsv",*verifier_args]
    code=subprocess.run(command).returncode
    if code not in (0,10):return code if code>=0 else 128-code
    if args.mode=="record":
        r=dict(schema=SCHEMA,rules=RULES,native_sha256=digest(binary),exit_code=code,sources=files,
               argv=list(map(str,command)),working_directory=str(Path.cwd()),
               tool_sha256={f:digest(tools/f) for f in TOOL_FILES},
               library_sha256={f:digest(out/f) for f in ("model.tsv","proof.bin")})
        save(out/"receipt.json",r)
        (out/"receipt.sha256").write_text(digest(out/"receipt.json")+"\n")
    elif not (out/"imports.tsv").is_file():
        # A frontend proof/early return can complete without a native query.
        # It has no first-boundary import and cannot claim attached clauses.
        if (out/"selected.tsv").exists() or (out/"ready.tsv").exists():
            raise RuntimeError("incomplete native import receipt")
        save(out/"no-boundary.json",dict(exit_code=code,selected=0,attached=0))
    return code


if __name__=="__main__":
    sys.exit(main())
