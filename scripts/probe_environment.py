"""Collect a Linux stage-0 snapshot. Uses local metadata and small public HTTP probes."""

import argparse
import json
import os
import platform
import resource
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def run(*argv):
    started = time.monotonic()
    result = {"argv": list(argv), "executable": shutil.which(argv[0])}
    if result["executable"] is None:
        return {**result, "status": "missing", "exit_code": None}
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                              env={**os.environ, "LC_ALL": "C"})
        result.update(status="exited", exit_code=proc.returncode,
                      stdout=proc.stdout.strip(), stderr=proc.stderr.strip())
    except subprocess.TimeoutExpired:
        result.update(status="timeout", exit_code=None)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def read_cgroup():
    membership = Path("/proc/self/cgroup").read_text().splitlines()
    mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    mount = next((line.split() for line in mounts if " - cgroup2 " in line), None)
    scope = next((s[3:] for s in membership if s.startswith("0::")), None)
    if not mount or scope is None:
        raise RuntimeError("This probe requires the target's unified cgroup v2 hierarchy")
    mount_root, mountpoint = Path(mount[3]), Path(mount[4])
    current = mountpoint / Path(scope).relative_to(mount_root)
    files = ("cpu.max", "cpuset.cpus.effective", "memory.max", "memory.high",
             "memory.current", "memory.swap.max", "pids.max")
    levels = []
    while True:
        values = {name: (current / name).read_text().strip() if (current / name).is_file()
                  else None for name in files}
        levels.append({"path": str(current), **values})
        if current == mountpoint:
            break
        current = current.parent
    return {"version": 2, "membership": membership, "mount_root": str(mount_root),
            "mountpoint": str(mountpoint), "ancestors_inclusive": levels}


def resource_snapshot():
    cgroup = read_cgroup()
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        if name in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            meminfo[name] = int(value.split()[0]) * 1024
    affinity = sorted(os.sched_getaffinity(0))
    cpu_caps = [len(affinity)]
    memory_caps = [meminfo["MemTotal"]]
    headrooms = [meminfo["MemAvailable"]]
    for level in cgroup["ancestors_inclusive"]:
        if level["cpu.max"]:
            quota, period = level["cpu.max"].split()
            if quota != "max":
                cpu_caps.append(int(quota) / int(period))
        if level["memory.max"] not in (None, "max"):
            limit = int(level["memory.max"])
            memory_caps.append(limit)
            headrooms.append(max(0, limit - int(level["memory.current"])))
    stat = os.statvfs(ROOT)
    model = next((line.split(":", 1)[1].strip() for line in
                  Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), None)
    return {
        "cpu": {"model": model, "os_cpu_count": os.cpu_count(), "affinity": affinity,
                "effective_logical_cpus": min(cpu_caps)},
        "memory": {"proc_meminfo_bytes": meminfo, "effective_total_bytes": min(memory_caps),
                   "effective_available_bytes": min(headrooms),
                   "rlimit_as_soft_hard_bytes": list(resource.getrlimit(resource.RLIMIT_AS))},
        "project_filesystem": {"path": str(ROOT), "total_bytes": stat.f_blocks * stat.f_frsize,
                               "available_bytes": stat.f_bavail * stat.f_frsize},
        "cgroup": cgroup,
    }


def network_probes(apt_inrelease):
    probes = [
        ("github_git_advertisement", "GET", "https://github.com/thufv/Deagle.git/info/refs?service=git-upload-pack"),
        ("github_metadata", "HEAD", "https://api.github.com/repos/thufv/Deagle"),
        ("github_source_archive", "HEAD", "https://codeload.github.com/thufv/Deagle/tar.gz/HEAD"),
        ("pypi", "HEAD", "https://pypi.org/simple/pip/"),
        ("deepseek_base", "HEAD", "https://api.deepseek.com/"),
    ]
    if apt_inrelease:
        probes.append(("apt_inrelease", "HEAD", apt_inrelease))

    def probe(item):
        name, method, url = item
        args = ["curl", "--disable", "--silent", "--show-error", "--location", "--max-redirs", "3",
                "--connect-timeout", "5", "--max-time", "12", "--output", "/dev/null",
                "--write-out", "http=%{http_code} type=%{content_type} elapsed_s=%{time_total}"]
        if method == "HEAD":
            args.append("--head")
        else:
            args.extend(["--header", "Git-Protocol: version=2"])
        return name, run(*args, url)

    with ThreadPoolExecutor(max_workers=4) as pool:
        return dict(pool.map(probe, probes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apt-inrelease", help="public InRelease URL from the active APT source")
    args = parser.parse_args()
    started, observed_at = time.monotonic(), utc_now()
    env = {
        "schema_version": 1, "stage": 0, "started_at_utc": observed_at,
        "project_root": str(ROOT), "uid": os.geteuid(),
        "os_release": dict(platform.freedesktop_os_release()),
        "kernel": platform.release(), "machine": platform.machine(),
        "resources": resource_snapshot(),
    }
    commands = {
        "architecture": ["dpkg", "--print-architecture"],
        "kernel": ["uname", "-smr"], "word_bits": ["getconf", "LONG_BIT"],
        "nproc": ["nproc"], "cpu_topology": ["lscpu", "-e=CPU,CORE,SOCKET,ONLINE"],
        "project_disk": ["df", "-B1", "-PT", str(ROOT)],
        "virtualization": ["systemd-detect-virt"],
        "docker_service": ["systemctl", "is-active", "docker.service"],
        "docker_server": ["docker", "info", "--format", "{{.ServerVersion}}"],
        "pip": ["python3", "-m", "pip", "--version"],
        "compiler_target": ["gcc", "-dumpmachine"],
    }
    for binary in ("git", "gcc", "g++", "make", "cmake", "flex", "bison", "python3",
                   "docker", "podman", "bwrap", "curl", "systemd-run", "timeout"):
        commands[binary] = [binary, "--version"]
    packages = ("build-essential", "gcc-multilib", "g++-multilib", "cmake", "flex", "bison",
                "python3-venv", "python3-pip", "libgoogle-perftools-dev", "libtcmalloc-minimal4")
    commands["installed_packages"] = [
        "dpkg-query", "-W", "-f", "${binary:Package}\t${db:Status-Abbrev}\t${Version}\n", *packages]
    commands["apt_candidates"] = ["apt-cache", "policy", *packages]
    env["commands"] = {name: run(*argv) for name, argv in commands.items()}
    env["docker_socket_present"] = Path("/var/run/docker.sock").is_socket()
    env["network"] = network_probes(args.apt_inrelease)
    env["finished_at_utc"] = utc_now()
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    env["probe_cost"] = {
        "wall_seconds": round(time.monotonic() - started, 3),
        "cpu_seconds_self_and_children": round(own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime, 3),
        "self_peak_rss_kib": own.ru_maxrss, "largest_waited_child_peak_rss_kib": children.ru_maxrss,
    }
    print(json.dumps(env, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
