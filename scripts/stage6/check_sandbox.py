"""Exercise the restricted mini tool surface on the real isolated host without a model."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.stage6.mini_repair import sandbox
from minisweagent.exceptions import Submitted
from incdeagle.model.identity import read, save
from incdeagle.repair_input import make_packet, packet_sha, public_text, wire_text
from scripts.stage6.mini_tools import RepairTools, SENTINEL, prepare


def check(run, out):
    request = read(run/"request.json")
    packet = make_packet(run/"snapshot"/request["case"],read(run/"repair/cex0.json"))
    env = sandbox()
    try:
        path = prepare(env,packet)
        tools = RepairTools(env)
        assert tools.execute({"command":"cat inputs/repair-context.json"})["output"]==wire_text(packet)
        assert tools.execute({"command":"cat candidate/program.c"})["output"]==packet["program.c"]
        denied = ["env","cat /proc/self/environ","cat /etc/shadow","cat ../apikey.txt",
                  "cat /root/private","cat candidate/program.c && env","cat inputs/raw.json"]
        for cmd in denied:
            result = tools.execute({"command":cmd})
            assert result["returncode"]==2 and cmd not in result["output"]
        fixture = '/* literal $(id) */\nint sample(void) { return 0; }\n'
        assert tools.execute({"command":"cat > candidate/program.c <<'C_SOURCE'\n"+fixture+"C_SOURCE"})["returncode"]==0
        assert path.read_text()==fixture
        assert tools.execute({"command":"sed -i 's/return 0/return 0/' candidate/program.c"})["returncode"]==0
        assert tools.execute({"command":"sed -i 's/x/y/e' candidate/program.c"})["returncode"]==2
        try:
            tools.execute({"command":"printf '%s\\n' "+SENTINEL+" 'offline test'"})
        except Submitted:
            pass
        else:
            raise AssertionError("Native mini submission did not finish")
        try:
            tools.execute({"command":"submit-line 2 'int sample(void) { return 1; }'"})
        except Submitted:
            assert path.read_text()==fixture.replace("return 0","return 1")
        else:
            raise AssertionError("Native one-line edit did not submit")
        for value in ("sk-"+"A"*24, "some-authentication-canary"):
            try:
                public_text(value,credential="some-authentication-canary")
            except ValueError:
                continue
            raise AssertionError("Sensitive content admitted")
        save(out,{"public_input_sha256":packet_sha(packet),"public_input_bytes":len(wire_text(packet).encode()),
                  "native_isolation_preflight":True,"allowed_reads":2,"denied_private_or_composed_commands":len(denied),
                  "quoted_source_roundtrip":True,"native_submit":True,"one_line_edit_and_submit":True,
                  "outbound_content_checks":2,"provider_calls":0})
    finally:
        env.cleanup()


if __name__=="__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("out",type=Path)
    a = p.parse_args()
    check(a.run,a.out)
