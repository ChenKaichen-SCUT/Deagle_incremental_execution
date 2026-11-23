"""Install the pinned mini source in a project venv, verifying wheels against PyPI."""
import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "third_party/mini-swe-agent"
WHEELS = ROOT / "runs/stage-01/wheels"
LOCK = ROOT / "configs/mini-requirements.lock"
PIP = "25.3"


def release(name, version):
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urlopen(Request(url, headers={"User-Agent": "stage1-wheel-verification"}), timeout=30) as reply:
        return {d["filename"]: d for d in json.load(reply)["urls"]}


def verify(wheel):
    with ZipFile(wheel) as archive:
        name, = [n for n in archive.namelist() if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
        meta = BytesParser().parsebytes(archive.read(name))
    package, version = meta["Name"], meta["Version"]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if release(package, version)[wheel.name]["digests"]["sha256"] != digest:
        raise ValueError(f"PyPI digest mismatch for {wheel.name}")
    return (f"{package}=={version}", digest, wheel.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", action="store_true", help="produce a new platform-specific hash lock")
    parser.add_argument("--index", default="https://pypi.org/simple")
    parser.add_argument("--file-mirror", help="optional base URL for fetching the bootstrap pip wheel")
    args = parser.parse_args()
    if sys.prefix == sys.base_prefix:
        raise SystemExit("Use the project venv Python")
    WHEELS.mkdir(parents=True, exist_ok=True)
    pip_wheel = WHEELS / f"pip-{PIP}-py3-none-any.whl"
    entry = release("pip", PIP)[pip_wheel.name]
    if not pip_wheel.exists():
        url = entry["url"]
        if args.file_mirror:
            url = args.file_mirror.rstrip("/") + urlsplit(url).path
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "2",
                        "--max-time", "120", "-o", str(pip_wheel), url], check=True)
    verify(pip_wheel)
    pip = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
    subprocess.run([*pip, "install", "--no-index", str(pip_wheel)], check=True)
    if args.resolve:
        # The bootstrap pip ships a TOML parser on Python 3.10.
        from pip._vendor import tomli
        spec = tomli.loads((SOURCE / "pyproject.toml").read_text())
        requirements = spec["project"]["dependencies"] + spec["build-system"]["requires"] + ["wheel"]
    else:
        requirements = ["--require-hashes", "-r", str(LOCK)]
    subprocess.run([*pip, "download", "--only-binary=:all:", "--progress-bar", "off", "--index-url", args.index,
                    "--dest", str(WHEELS), *requirements], check=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        verified = sorted(pool.map(verify, WHEELS.glob("*.whl")))
    lock = "\n".join(f"{spec} --hash=sha256:{sha}" for spec, sha, _ in verified) + "\n"
    if args.resolve:
        LOCK.write_text(lock)
    report = ROOT / "runs/stage-01/verified-wheels.json"
    report.write_text(json.dumps([dict(requirement=s, sha256=h, filename=f) for s, h, f in verified], indent=2) + "\n")
    subprocess.run([*pip, "install", "--no-index", "--find-links", str(WHEELS), "--require-hashes", "-r", str(LOCK)], check=True)
    subprocess.run([*pip, "install", "--no-index", "--no-deps", "--no-build-isolation", "-e", str(SOURCE)], check=True)
    subprocess.run([*pip, "check"], check=True)


if __name__ == "__main__":
    main()
