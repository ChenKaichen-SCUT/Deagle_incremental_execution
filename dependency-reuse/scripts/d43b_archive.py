"""Losslessly pack or read B evidence, sharing verified 4 MiB chunks with frozen D4.2 and A."""
import argparse
import gzip
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from d4_archive import CHUNK, safe, sha

EVIDENCE = Path(__file__).resolve().parents[1] / "reports/evidence"
BASES = {
    "D42": ("d42/raw/release", "45e21554e55b97dcb64aa68095c19acf7221656c7a18388f261aff78a82a96c2"),
    "D43A": ("d43a/raw", "571c0203ef13f9bf614c6b12687c58a0638254cc869c27e28d3854c08b50619d"),
}


def base_objects():
    known = {}
    for label, (directory, digest) in BASES.items():
        data = (EVIDENCE / directory / "files.json").read_bytes()
        if sha(data) != digest:
            raise ValueError("wrong parent index " + label)
        for entry in json.loads(data)["files"].values():
            for block in entry["chunks"]:
                known.setdefault(block, label)
    return known


def pack(root, sources):
    (root / "objects").mkdir(parents=True, exist_ok=False)
    parent = base_objects()
    files, owners = {}, {}
    for item in sources:
        label, original = item.split("=", 1)
        base = Path(original).resolve(strict=True)
        paths = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for path in paths:
            name = label if path == base else label + "/" + path.relative_to(base).as_posix()
            safe(root, name)
            if name in files:
                raise ValueError("duplicate file " + name)
            length, chunks, total = 0, [], hashlib.sha256()
            with path.open("rb") as source:
                for data in iter(lambda: source.read(CHUNK), b""):
                    block = sha(data)
                    length += len(data)
                    chunks.append(block)
                    total.update(data)
                    if block in owners:
                        continue
                    owners[block] = parent.get(block, "B")
                    if owners[block] == "B":
                        (root / "objects" / (block + ".gz")).write_bytes(gzip.compress(data, compresslevel=5, mtime=0))
            files[name] = dict(bytes=length, sha256=total.hexdigest(), chunks=chunks)
    index = dict(format="D43B-raw-v1", chunk_bytes=CHUNK, bases=BASES, files=files, owners=owners)
    (root / "files.json").write_text(json.dumps(index, indent=2) + "\n")


def verify(root, prefix, dest):
    index = json.loads((root / "files.json").read_bytes())
    if (index["format"], index["chunk_bytes"], index["bases"]) != (
            "D43B-raw-v1", CHUNK, {k:list(v) for k,v in BASES.items()}):
        raise ValueError("incompatible archive")
    parents = base_objects()

    @lru_cache(maxsize=12)
    def chunk(block):
        if len(block) != 64 or any(c not in "0123456789abcdef" for c in block):
            raise ValueError("malformed object id")
        owner = index["owners"][block]
        if owner != parents.get(block, "B"):
            raise ValueError("wrong object directory")
        directory = root if owner == "B" else EVIDENCE / BASES[owner][0]
        data = gzip.decompress((directory / "objects" / (block + ".gz")).read_bytes())
        if len(data) > CHUNK or sha(data) != block:
            raise ValueError("corrupt object " + block)
        return data

    count = original = 0
    for name, entry in index["files"].items():
        if prefix and name != prefix and not name.startswith(prefix.rstrip("/") + "/"):
            continue
        total = hashlib.sha256()
        length = 0
        output = None
        if dest:
            path = safe(dest, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            output = path.open("xb")
        try:
            for block in entry["chunks"]:
                data = chunk(block)
                total.update(data)
                length += len(data)
                if output:
                    output.write(data)
        finally:
            if output:
                output.close()
        if (length, total.hexdigest()) != (entry["bytes"], entry["sha256"]):
            raise ValueError("damaged file " + name)
        count += 1
        original += length
    if not count:
        raise ValueError("empty selection")
    print(f"{count} files, {original} original bytes verified")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    p = sub.add_parser("pack")
    p.add_argument("archive", type=Path)
    p.add_argument("sources", nargs="+", metavar="LABEL=PATH")
    for name in ("verify", "restore"):
        p = sub.add_parser(name)
        p.add_argument("archive", type=Path)
        p.add_argument("--prefix", default="")
        if name == "restore":
            p.add_argument("new_directory", type=Path)
    a = ap.parse_args()
    if a.action == "pack":
        pack(a.archive.resolve(), a.sources)
    else:
        dest = a.new_directory.resolve() if a.action == "restore" else None
        if dest:
            dest.mkdir(parents=True, exist_ok=False)
        verify(a.archive.resolve(), a.prefix, dest)
