"""Rebuild both native artifacts from fixed Git objects and compare their runtime sections."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCES = {
    "production": "998c4f9a845d6f59bed5c3cfc96b5ee56181a0a1",
    "observer": "dbe6e1650fe2803349bfade2eefaaa46d9262506",
}
SECTIONS = (".text", ".rodata", ".data", ".init_array", ".eh_frame", ".gcc_except_table")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebuild(repo, work, output):
    results = {}
    for kind, source in SOURCES.items():
        original = work / ("bin" if kind == "production" else "audit-build") / "pi1"
        with tempfile.TemporaryDirectory() as name:
            temp = Path(name)
            inputs = ["minisat-2.2.1", "persistent-solver/include", "persistent-solver/src",
                      "persistent-solver/scripts/build-pi1.sh", "src/util"]
            with (temp / "source.tar").open("wb") as archive:
                subprocess.run(["git", "-C", repo, "archive", source, *inputs], stdout=archive, check=True)
            subprocess.run(["tar", "-xf", "source.tar"], cwd=temp, check=True)
            env = dict(os.environ, PI1G_OBSERVER_BUILD="1" if kind == "observer" else "0")
            subprocess.run(["bash", "persistent-solver/scripts/build-pi1.sh", temp/"build"],
                           cwd=temp, env=env, check=True)
            rebuilt = temp / "build/pi1"
            verified = {}
            for section in SECTIONS:
                hashes = []
                for binary in (original, rebuilt):
                    subprocess.run(["objcopy", "-O", "binary", "--only-section="+section, binary, temp/"section"], check=True)
                    assert (temp/"section").stat().st_size > 0
                    hashes.append(digest(temp/"section"))
                assert hashes[0] == hashes[1], (source, section)
                verified[section] = hashes[0]
            symbols = subprocess.check_output(["nm", "-C", original], text=True)
            has_observer = " T Minisat::NativeLedger::measureBirth(" in symbols
            assert has_observer == (kind == "observer")
            results[kind] = dict(source=source, original_elf_sha256=digest(original), rebuilt_elf_sha256=digest(rebuilt),
                                 runtime_sections_sha256=verified, has_birth_observer=has_observer)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2)+"\n")


if __name__ == "__main__":
    rebuild(*(Path(v) for v in sys.argv[1:]))
