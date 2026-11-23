"""Check one isolated file edit and a real mini/DeepSeek tool-result round trip."""
import argparse
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

os.environ["MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT"] = "1"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm
import yaml
from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.extra.bubblewrap import BubblewrapEnvironment
from minisweagent.models.litellm_model import LitellmModel

from run_evidence import ROOT, RUN, write_json


class RecordedModel(LitellmModel):
    """Keep the credential out of mini's serializable config and prompt variables."""

    def __init__(self, key, **kwargs):
        super().__init__(**kwargs)
        self._key = key
        self.requests = []
        self._previous_reasoning = None

    def _query(self, messages, **kwargs):
        earlier = [m for m in messages if m["role"] == "assistant"]
        preserved = None
        if self._previous_reasoning is not None:
            preserved = bool(earlier and earlier[-1].get("reasoning_content") == self._previous_reasoning)
            if not preserved:
                raise ValueError("Tool-call reasoning was lost before the next request")
        ticket = {
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "roles": [m["role"] for m in messages],
            "returned_tool_ids": [m["tool_call_id"] for m in messages if m["role"] == "tool"],
            "prior_reasoning_present": any(bool(m.get("reasoning_content")) for m in messages),
            "prior_reasoning_exact": preserved,
        }
        self.requests.append(ticket)
        response = super()._query(messages, api_key=self._key, **kwargs)
        usage = response.usage.model_dump()
        message = response.choices[0].message
        self._previous_reasoning = getattr(message, "reasoning_content", None)
        ticket.update({
            "response_id": response.id, "returned_model": response.model,
            "finish_reason": response.choices[0].finish_reason,
            "reasoning_present": bool(getattr(message, "reasoning_content", None)),
            "tool_calls": [{"id": t.id, "tool": t.function.name, "arguments": t.function.arguments}
                           for t in message.tool_calls or []],
            "input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"],
            "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", (usage.get("prompt_tokens_details") or {}).get("cached_tokens")),
            "cache_miss_tokens": usage.get("prompt_cache_miss_tokens"),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        })
        return response


def sandbox():
    # setpriv drops the host identity before bwrap creates the user, PID and network namespaces.
    args = ["--reuid=65534", "--regid=65534", "--clear-groups", "--no-new-privs", "/usr/bin/bwrap",
            "--unshare-all", "--uid", "65534", "--gid", "65534", "--cap-drop", "ALL", "--die-with-parent",
            "--new-session", "--clearenv", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
            "--dir", "/bin", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--setenv", "PATH", "/bin"]
    for tool in ("bash", "cat", "id", "ls"):
        args += ["--ro-bind", "/usr/bin/" + tool, "/bin/" + tool]
    env = BubblewrapEnvironment(executable="/usr/bin/setpriv", wrapper_args=args, timeout=10)
    os.chown(env.working_dir, 65534, 65534)
    env.working_dir.chmod(0o700)
    return env


def estimate(requests, rates):
    amount = Decimal(0)
    for req in requests:
        hit = req.get("cache_hit_tokens")
        if hit is None or "output_tokens" not in req:
            return None
        miss = req["input_tokens"] - hit
        if req.get("cache_miss_tokens") not in (None, miss):
            raise ValueError("Cache counters disagree")
        amount += sum(Decimal(str(rates[k])) * n for k, n in
                      (("cache_hit", hit), ("cache_miss", miss), ("output", req["output_tokens"])))
    return str(amount / 1000000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-stdin", action="store_true", help="take the controller key on private stdin")
    parser.add_argument("--isolation-only", action="store_true")
    args = parser.parse_args()
    cfg = yaml.safe_load((ROOT / "configs/deepseek.yaml").read_text())
    if cfg["base_url"] != "https://api.deepseek.com":
        raise ValueError("Expected the official API base")
    visible = json.loads((ROOT / "reports/evidence/stage-01/models.json").read_text())["model_ids"]
    if cfg["model_id"] not in visible:
        raise ValueError("Selected model absent from the recorded /models response")
    env = sandbox()
    receipt = "ack-" + secrets.token_hex(8)
    initial = {"status.txt": "pending\n", "receipt.txt": receipt + "\n"}
    record = {"started_utc": datetime.now(timezone.utc).isoformat(), "model": cfg["model_id"],
              "route": cfg["litellm_route"], "api_base": cfg["base_url"], "requests": [],
              "prompt_receipt_supplied": False, "status_before": "pending"}
    destination = RUN / ("mini-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    try:
        for name, content in initial.items():
            p = env.working_dir / name
            p.write_text(content)
            os.chown(p, 65534, 65534)
        os.environ["INCDEAGLE_CONTROL_CANARY"] = "host-only"
        check = env.execute({"command":
            'set -eu; test "$(id -u)" = 65534; test -z "${INCDEAGLE_CONTROL_CANARY+x}"; '
            'test -z "${DEEPSEEK_API_KEY+x}"; test ! -e /root/Deagle_incremental_execution; '
            'test ! -e /etc/shadow; test ! -w /bin/bash; test -w status.txt; : > uid-proof; '
            'printf "uid=%s\\n" "$(id -u)"; cat /proc/self/uid_map; cat /proc/net/route'})
        record["isolation"] = check
        if check["returncode"] != 0 or len(check["output"].splitlines()) != 3:
            raise RuntimeError("Isolation preflight failed")
        proof = env.working_dir / "uid-proof"
        record["host_uid_of_sandbox_created_file"] = proof.stat().st_uid
        if proof.stat().st_uid != 65534:
            raise RuntimeError("Wrong host identity for sandbox files")
        proof.unlink()
        if args.isolation_only:
            record["result"] = "isolation_passed"
            return
        key = (sys.stdin.readline() if args.key_stdin else (ROOT / "apikey.txt").read_text()).strip()
        if not key:
            raise ValueError("Empty controller key")
        rates = cfg["pricing"]["per_million_tokens"]
        route = cfg["litellm_route"]
        litellm.register_model({route: {**litellm.model_cost.get(route, {}), "litellm_provider": "deepseek",
            "mode": "chat", "input_cost_per_token": rates["peak"]["cache_miss"] / 1e6,
            "cache_read_input_token_cost": rates["peak"]["cache_hit"] / 1e6,
            "output_cost_per_token": rates["peak"]["output"] / 1e6}})
        model = RecordedModel(key, model_name=route, cost_tracking="ignore_errors", model_kwargs={
            "api_base": cfg["base_url"], "timeout": 60, "max_tokens": 1536, "num_retries": 0,
            "reasoning_effort": cfg["smoke"]["reasoning_effort"], "extra_body": {"thinking": {"type": "enabled"}}})
        record["requests"] = model.requests
        agent = DefaultAgent(model, env, system_template="Run the two specified protocol steps in order. Use one native bash tool call per response.",
            instance_template="{{ task }}", step_limit=cfg["smoke"]["max_model_calls"], cost_limit=0,
            wall_time_limit_seconds=cfg["smoke"]["timeout_seconds"], max_consecutive_format_errors=1)
        result = agent.run(task=(
            "The shell is already in the directory containing status.txt and receipt.txt. "
            "Step 1: execute this exact command now, with no discovery commands: "
            "printf '%s\\n' ready > status.txt && cat receipt.txt\n"
            "Step 2: after you receive its output, execute: "
            "printf '%s\\n' COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT RECEIPT\n"
            "Replace RECEIPT with the literal ack-... value printed by step 1."))
        record.update(exit_status=result["exit_status"], submission=result["submission"].strip(),
                      status_after=(env.working_dir / "status.txt").read_text(),
                      observations=[{"tool_call_id": m["tool_call_id"], "output": m["extra"]["raw_output"],
                                     "returncode": m["extra"]["returncode"]} for m in agent.messages if m["role"] == "tool"],
                      agent_calls=agent.n_calls)
        calls = model.requests
        passed = (result["exit_status"] == "Submitted" and result["submission"].strip() == receipt
                  and record["status_after"] == "ready\n" and (env.working_dir / "receipt.txt").read_text() == initial["receipt.txt"]
                  and len(calls) >= 2 and any(receipt in c["arguments"] for c in calls[-1]["tool_calls"])
                  and any(o["returncode"] == 0 and receipt in o["output"] and o["tool_call_id"] in calls[-1]["returned_tool_ids"]
                          for o in record["observations"]))
        record["estimated_usd_by_tariff"] = {k: estimate(calls, v) for k, v in rates.items()}
        record["result"] = "passed" if passed else "failed"
        if not passed:
            raise RuntimeError("File edit or tool-result round trip failed")
    except Exception as exc:
        record.update(error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None), result="failed")
        raise
    finally:
        env.cleanup()
        write_json(destination, record)
        print(destination)


if __name__ == "__main__":
    main()
