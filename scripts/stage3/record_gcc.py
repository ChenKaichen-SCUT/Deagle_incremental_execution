#!/usr/bin/python3
"""Record GCC line-marker dependencies; forward the actual preprocessor output verbatim."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

GCC = "/usr/bin/gcc"
args = sys.argv[1:]
if "-E" not in args or not args or not Path(args[-1]).is_file():
    os.execv(GCC, [GCC, *args])
result = subprocess.run([GCC, *args], stdout=subprocess.PIPE)
source = Path(args[-1]).resolve()
digest = lambda data: hashlib.sha256(data).hexdigest()
marker = re.compile(rb'(?m)^#\s+\d+\s+"([^"\n]+)"')
deps = {}
unit = "harness.c" if source == Path("harness.c").resolve() else "generated/" + digest(source.read_bytes())


def record(match):
    spelling = os.fsdecode(match[1])
    path = Path(spelling)
    if spelling.startswith("<") or not path.is_file():
        return match[0]
    path = path.resolve()
    name = unit if path == source else (path.name if path.parent == Path.cwd() else str(path))
    deps[name] = digest(path.read_bytes())
    return match[0].replace(match[1], os.fsencode(name))


stable = marker.sub(record, result.stdout)
with open(os.environ["INCDEAGLE_CPP_RECORD"], "a", encoding="utf-8") as stream:
    print(json.dumps({"unit": unit, "argv": [*args[:-1], unit], "raw_argv": args,
                      "files": deps, "returncode": result.returncode,
                      "raw_output_sha256": digest(result.stdout), "output_sha256": digest(stable)}), file=stream)
sys.stdout.buffer.write(result.stdout)
sys.exit(result.returncode)
