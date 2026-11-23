"""Generate a single candidate using the pinned mini agent and minimal P0 evidence."""
import argparse
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"scripts/stage1"))
import yaml
from incdeagle.model.identity import file_sha, read, save
from incdeagle.repair_input import make_packet, packet_sha, public_text, wire_text
from mini_smoke import DefaultAgent, RecordedModel, estimate, litellm, sandbox
from scripts.stage6.mini_tools import INSTRUCTIONS, SYSTEM, RepairTools, prepare, sha


def now():
    return datetime.now(timezone.utc).isoformat()


class ScopedModel(RecordedModel):
    def _query(self, messages, **kwargs):
        encoded = public_text(wire_text(messages),131072,self._key)
        response = super()._query(messages,**kwargs)
        ticket = self.requests[-1]
        ticket.update(wire_messages_sha256=sha(encoded),wire_messages_bytes=len(encoded.encode()))
        for call in ticket["tool_calls"]:
            arguments = call.pop("arguments")
            call.update(arguments_sha256=sha(arguments),arguments_bytes=len(arguments.encode()))
        return response


def run(directory, key_stdin):
    request = read(directory/"request.json")
    case = directory/"snapshot"/request["case"]
    repair = directory/"repair"
    cfg = yaml.safe_load((ROOT/"configs/deepseek.yaml").read_bytes())
    rates = cfg["pricing"]["per_million_tokens"]
    record = {"started_utc":now(),"case":case.name,"requests":[],"exit_status":"Failed"}
    env = None
    try:
        if (cfg["base_url"]!="https://api.deepseek.com" or cfg["litellm_route"]!="deepseek/"+cfg["model_id"]
                or cfg["model_id"] not in read(ROOT/"reports/evidence/stage-01/models.json")["model_ids"]):
            raise ValueError("Unknown model or endpoint")
        packet = make_packet(case,read(repair/"cex0.json"))
        fingerprint = packet_sha(packet)
        save(repair/"model-input.json",packet)
        record.update(model_input_sha256=fingerprint,model_input_bytes=len(wire_text(packet).encode()),
                      model=cfg["model_id"],api_base=cfg["base_url"],route=cfg["litellm_route"],
                      system_prompt=SYSTEM,task_instructions=INSTRUCTIONS)
        if request.get("repair_input_sha256",fingerprint)!=fingerprint:
            record["error_reason"]="approved_input_digest_mismatch"
            raise ValueError("Different public input")
        env = sandbox()
        final = prepare(env,packet)
        tools = RepairTools(env)
        record.update(preflight={"restricted_uid":65534,"no_network_route":True,"packet_read_only":True,
                                 "candidate_writable":True,"host_project_absent":True,"sandbox_auth_env_absent":True})
        key = (sys.stdin.readline() if key_stdin else (ROOT/cfg["controller_key_file"]).read_text(encoding="utf-8-sig")).strip()
        if not key:
            record["error_reason"]="empty_controller_credential"
            raise ValueError("Empty controller credential")
        route = cfg["litellm_route"]
        litellm.telemetry = False
        litellm.register_model({route:{**litellm.model_cost.get(route,{}),"litellm_provider":"deepseek","mode":"chat",
                                     "input_cost_per_token":rates["peak"]["cache_miss"]/1e6,
                                     "cache_read_input_token_cost":rates["peak"]["cache_hit"]/1e6,
                                     "output_cost_per_token":rates["peak"]["output"]/1e6}})
        model = ScopedModel(key,model_name=route,cost_tracking="ignore_errors",model_kwargs={
            "api_base":cfg["base_url"],"timeout":60,"max_tokens":2048,"num_retries":0,
            "reasoning_effort":"low","extra_body":{"thinking":{"type":"enabled"}}})
        limit,wall = min(4,cfg["repair"]["max_model_calls"]),min(300,cfg["repair"]["timeout_seconds"])
        record.update(max_model_calls=limit,timeout_seconds=wall,automatic_retries=0)
        agent = DefaultAgent(model,tools,system_template=SYSTEM,instance_template="{{ task }}",
                             step_limit=limit,cost_limit=0,wall_time_limit_seconds=wall,max_consecutive_format_errors=1)
        try:
            result = agent.run(task=INSTRUCTIONS+wire_text(packet))
        finally:
            record["requests"] = model.requests
            record["operations"] = tools.operations
        record["exit_status"] = result["exit_status"]
        if record["exit_status"]!="Submitted":
            record["error_reason"] = record["exit_status"]
            raise ValueError("No submitted candidate")
        record["submission"] = public_text(result["submission"].strip(),512,key)
        if file_sha(env.working_dir/"inputs/repair-context.json")!=fingerprint:
            raise ValueError("Public input changed")
        mode = final.lstat()
        if sorted(p.name for p in final.parent.iterdir())!=["program.c"] or not stat.S_ISREG(mode.st_mode) or mode.st_nlink!=1:
            raise ValueError("Unexpected candidate files")
        data = final.read_bytes()
        public_text(data.decode("utf-8"),credential=key)
        if not data or data==(case/"old/program.c").read_bytes():
            raise ValueError("Empty or unchanged submission")
        with (repair/"submitted.c").open("xb") as stream:
            stream.write(data)
        record["candidate_sha256"] = file_sha(repair/"submitted.c")
        record["protected_inputs_unchanged"] = True
        return 0
    except Exception as exc:
        record.update(exit_status="Failed",error=type(exc).__name__,http_status=getattr(exc,"status_code",None))
        return 1
    finally:
        if env is not None:
            env.cleanup()
        record.update(finished_utc=now(),estimated_usd_by_tariff={k:estimate(record["requests"],v) for k,v in rates.items()})
        save(repair/"model.json",record)


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    parser.add_argument("--key-stdin",action="store_true")
    args = parser.parse_args()
    sys.exit(run(args.run,args.key_stdin))
