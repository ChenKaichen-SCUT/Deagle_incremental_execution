"""Generate one repair for the synthetic two-contribution case from P0 evidence."""
import argparse
import gzip
import hashlib
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from check_case import ROOT, load_case
from mini_smoke import DefaultAgent, RecordedModel, estimate, litellm, sandbox
from run_evidence import sha256, write_json
import yaml

SYSTEM = ("You are repairing an arithmetic tally in a small pthreads exercise. Use the native bash tool. "
          "Return one final candidate and a short public explanation. Do not change the test or the domain contract.")


def put(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o444)


def prepare(case):
    task, gamma, phi = load_case(case)
    old = case / "evidence/old"
    cex = json.loads((old / "cex0.json").read_bytes())
    prior = json.loads((old / "run.json").read_bytes())
    raw = gzip.decompress((old / cex["raw_trace"]).read_bytes())
    if prior["classification"] != "VIOLATION" or prior["input_sha256"]["program.c"] != sha256(case / task["old_source"]):
        raise ValueError("The counterexample does not belong to this old program")
    if cex["gamma"] != gamma or cex["p0_sha256"] != prior["input_sha256"]["program.c"] or hashlib.sha256(raw).hexdigest() != prior["runs"]["verify"]["document_sha256"]:
        raise ValueError("Mismatched counterexample, configuration or raw document")
    env = sandbox()
    try:
        for name in ("sed", "head", "tail", "grep", "diff", "wc", "gcc"):
            env.config.wrapper_args += ["--ro-bind", "/usr/bin/" + name, "/bin/" + name]
        for path in ("/usr/lib/gcc", "/usr/include"):
            env.config.wrapper_args += ["--ro-bind", path, path]
        work = env.working_dir
        os.chown(work, 0, 0)
        work.chmod(0o755)
        inputs = work / "inputs"
        files = {name: (case / name).read_bytes() for name in ("harness.c", "phi.json", "gamma.json", "task.yaml", task["old_source"])}
        files["cex0.json"] = (old / "cex0.json").read_bytes()
        files["raw.json"] = raw
        for name, content in files.items():
            put(inputs / name, content)
        for directory in (inputs / "old", inputs):
            directory.chmod(0o555)
        output = work / "candidate"
        output.mkdir(mode=0o755)
        os.chown(output, 65534, 65534)
        candidate = output / "program.c"
        candidate.write_bytes(files[task["old_source"]])
        os.chown(candidate, 65534, 65534)
        preflight = env.execute({"command":
            'set -eu; test "$(id -u)" = 65534; test ! -w .; test ! -w inputs/harness.c; '
            'test ! -w inputs; test -w candidate/program.c; test ! -e /root/Deagle_incremental_execution; '
            'test -z "${DEEPSEEK_API_KEY+x}"; test "$(wc -l < /proc/net/route)" -eq 1; '
            'gcc -std=gnu11 -pthread -fsyntax-only -I candidate inputs/harness.c; printf "isolated syntax check passed\\n"'})
        if preflight["returncode"] or "isolated syntax check passed" not in preflight["output"]:
            raise RuntimeError("Sandbox preflight: " + preflight["output"])
        observations = [{"index":s["index"], "thread":s["thread"], "line":s["source"].get("line"),
                         "lhs":s["lhs"], "value":s["value"].get("data")}
                        for s in cex["steps"] if s["source"].get("file") == "program.c" and s.get("lhs") in ("counter", "snapshot")]
        prompt = (
            "The original unmodified snapshot is in inputs/old/program.c. This is a closed exercise: no inputs or files "
            "outside this workspace are needed. Edit only candidate/program.c, which is initially an exact copy. "
            "Read the original harness, including both workers, and preserve its functionality. The protected files "
            "inputs/harness.c, inputs/phi.json, inputs/gamma.json and inputs/task.yaml contain the original "
            "property, assumptions and verification configuration. inputs/cex0.json contains the complete normalized "
            "counterexample and inputs/raw.json the full native result. They are available if you need more detail. "
            "Do not weaken the property, add assumptions, skip work, change thread creation, hardcode the final total "
            "or bypass either worker. Perform a small source edit based on the evidence and preserve one contribution per call. "
            "Use bash, cat, sed, diff and gcc as needed. Optional syntax command: "
            "gcc -std=gnu11 -pthread -fsyntax-only -I candidate inputs/harness.c. "
            "When the single candidate is ready, use a separate bash call: "
            "printf '%s\\n' COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT 'your brief change explanation'. "
            "The controller derives cases/split_counter/patch.diff from your submitted file. "
            "The formal verifier is outside this workspace. Do not request its result.\n"
            f"Property: {phi['description']} Target: {phi['id']} at {phi['source']}. "
            f"SC, 64-bit, unwind 4, unwinding assertions enabled. Relevant observations in original UI order: {json.dumps(observations)}.")
        return env, files, prompt, preflight
    except BaseException:
        env.cleanup()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=["split_counter"])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--key-stdin", action="store_true")
    group.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    case = ROOT / "cases" / args.case
    candidate = case / "candidate/program.c"
    if not args.preflight and candidate.exists():
        raise SystemExit("A candidate already exists for this case")
    cfg = yaml.safe_load((ROOT / "configs/deepseek.yaml").read_bytes())
    if cfg["base_url"] != "https://api.deepseek.com" or cfg["model_id"] not in json.loads((ROOT / "reports/evidence/stage-01/models.json").read_bytes())["model_ids"]:
        raise ValueError("Unverified endpoint or model")
    env, inputs, prompt, preflight = prepare(case)
    destination = ROOT / "reports/evidence/stage-02" / ("mini-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    record = {"started_utc": datetime.now(timezone.utc).isoformat(), "case": args.case, "stage": 2,
              "api_base": cfg["base_url"], "model": cfg["model_id"], "route": cfg["litellm_route"],
              "sandbox_preflight": preflight, "system_prompt": SYSTEM, "task_prompt": prompt,
              "input_sha256": {k: hashlib.sha256(v).hexdigest() for k, v in inputs.items()}, "requests": []}
    try:
        if args.preflight:
            print(preflight["output"].strip())
            return
        key = sys.stdin.readline().strip()
        if not key:
            raise ValueError("Empty API credential")
        rates = cfg["pricing"]["per_million_tokens"]
        route = cfg["litellm_route"]
        litellm.register_model({route: {**litellm.model_cost.get(route, {}), "litellm_provider": "deepseek", "mode": "chat",
            "input_cost_per_token": rates["peak"]["cache_miss"]/1e6, "cache_read_input_token_cost": rates["peak"]["cache_hit"]/1e6,
            "output_cost_per_token": rates["peak"]["output"]/1e6}})
        model = RecordedModel(key, model_name=route, cost_tracking="ignore_errors", model_kwargs={
            "api_base":cfg["base_url"], "timeout":60, "max_tokens":2048, "num_retries":0,
            "reasoning_effort":"low", "extra_body":{"thinking":{"type":"enabled"}}})
        del key
        record["requests"] = model.requests
        record["limits"] = {"max_model_calls": min(8, cfg["repair"]["max_model_calls"]),
                            "wall_seconds": min(300, cfg["repair"]["timeout_seconds"]), "automatic_retries": 0}
        agent = DefaultAgent(model, env, system_template=SYSTEM, instance_template="{{ task }}",
                            step_limit=record["limits"]["max_model_calls"], cost_limit=0,
                            wall_time_limit_seconds=record["limits"]["wall_seconds"], max_consecutive_format_errors=1)
        result = agent.run(task=prompt)
        record["exit_status"] = result["exit_status"]
        record["submission"] = result["submission"].strip()
        record["observations"] = [{"tool_call_id":m["tool_call_id"], "returncode":m["extra"]["returncode"],
                                   "output":m["extra"]["raw_output"]} for m in agent.messages if m["role"] == "tool"]
        if result["exit_status"] != "Submitted" or not record["submission"]:
            raise RuntimeError("No submitted candidate")
        for name, expected in inputs.items():
            if (env.working_dir / "inputs" / name).read_bytes() != expected:
                raise ValueError("A protected input changed")
        output = env.working_dir / "candidate"
        final = output / "program.c"
        st = final.lstat()
        if sorted(p.name for p in output.iterdir()) != ["program.c"] or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError("Unexpected candidate files")
        if not (0 < st.st_size < 32768) or final.read_bytes() == inputs["old/program.c"]:
            raise ValueError("Empty, unchanged or oversized candidate")
        record["candidate_sha256"] = sha256(final)
        candidate.parent.mkdir(exist_ok=True)
        with candidate.open("xb") as stream:
            stream.write(final.read_bytes())
        record["protected_inputs_unchanged"] = True
        record["output_files"] = ["program.c"]
        record["result"] = "submitted"
    except Exception as exc:
        record.update(result="failed", error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
        raise
    finally:
        env.cleanup()
        if not args.preflight:
            record["finished_utc"] = datetime.now(timezone.utc).isoformat()
            record["estimated_usd_by_tariff"] = {k: estimate(record["requests"], v) for k, v in cfg["pricing"]["per_million_tokens"].items()}
            write_json(destination, record)
            print(destination)


if __name__ == "__main__":
    main()
