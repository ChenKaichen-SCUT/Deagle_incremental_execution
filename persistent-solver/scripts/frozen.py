"""Read PI-0 diagnostic inputs from immutable Git objects in the research repository."""
import hashlib
import json
import subprocess
from pathlib import Path

UPSTREAM = "d8c79eaba5df03b1a013dc6ffbb3a1e249485c1e"
TREE = "ee983048136026478a6af5774ab20077b273db2f"
RESEARCH = "d764b47976574a9302dd82bb9442b0e62c7466fa"
STOCK = "f8c08f379f3777f7ef36e197346e6fdcef3fa57aa71c35f40d7ef587010ed7ab"
CASES = ("fib_updates_8", "circular-buffer", "airline_reservations_6", "fib-snapshot-11")


def blob(repo, relative):
    return subprocess.check_output(
        ["git", "-C", str(repo), "cat-file", "blob", RESEARCH + ":dependency-reuse/" + relative])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
