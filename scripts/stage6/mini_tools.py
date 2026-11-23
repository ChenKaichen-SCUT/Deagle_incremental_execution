"""Restrict mini's native Bash environment to the two files needed for the repair."""
import hashlib
import os
import re
import shlex

from incdeagle.repair_input import public_text, wire_text


SYSTEM = "Repair the given concurrent C program. Use one native bash tool call per response."
INSTRUCTIONS = (
    "The JSON below contains the complete editable function and relevant evidence from the old program. "
    "Preserve the computation, arguments, thread work and contract. Avoid hardcoding the final total or adding assumptions. "
    "For a one-line repair, use the bash tool now with ONE command: "
    "submit-line N 'replacement C line'. N is the 1-based line number in program.c. Supply your own "
    "complete corrected line inside single quotes. This writes and submits the patch immediately. "
    "For a multiline repair, write your corrected complete C source using:\n"
    "cat > candidate/program.c <<'C_SOURCE'\n<your complete corrected source>\nC_SOURCE\n"
    "After a multiline write, use: submit 'brief repair description'\n"
    "Optional reads are cat candidate/program.c and cat inputs/repair-context.json.\n"
)
SENTINEL = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class RepairTools:
    """Only the packet, candidate and fixed status messages can become model observations."""

    def __init__(self, env):
        self.env = env
        self.operations = []

    def get_template_vars(self):
        return {}

    def serialize(self):
        return {}

    def write(self, data):
        public_text(data)
        # Quoting is performed here even if the source contains shell metacharacters.
        result = self.env.execute({"command":"printf %s "+shlex.quote(data)+" > candidate/program.c"})
        if result["returncode"]:
            return False
        self.operations.append({"operation":"write","file":"candidate/program.c","sha256":sha(data)})
        return True

    def submit(self, note):
        public_text(note,512)
        self.operations.append({"operation":"submit","description_sha256":sha(note)})
        return self.env.execute({"command":shlex.join(["printf","%s\\n",SENTINEL,note])})

    def execute(self, action):
        cmd = action.get("command","").strip()
        denied = {"returncode":2,"output":"For a one-line change use: submit-line N 'your complete replacement C line'","exception_info":""}
        if cmd in ("cat candidate/program.c","cat inputs/repair-context.json"):
            result = self.env.execute({"command":cmd})
            if result["returncode"]:
                return denied
            data = public_text(result["output"])
            self.operations.append({"operation":"read","file":cmd[4:],"sha256":sha(data)})
            return {"returncode":0,"output":data,"exception_info":""}
        lines = cmd.split("\n")
        delimiter = r"""['"]?([A-Za-z_][A-Za-z0-9_]{0,31})['"]?"""
        here = (re.fullmatch(r"cat\s*>\s*candidate/program\.c\s*<<\s*"+delimiter,lines[0]) or
                re.fullmatch(r"cat\s*<<\s*"+delimiter+r"\s*>\s*candidate/program\.c",lines[0]))
        if len(lines)>=3 and here and lines[-1]==here.group(1):
            if not self.write("\n".join(lines[1:-1])+"\n"):
                return denied
            return {"returncode":0,"output":"candidate/program.c saved\n","exception_info":""}
        try:
            args = shlex.split(cmd)
        except ValueError:
            args = []
        if len(args)==5 and args[:3]==["sed","-i","-e"]:
            args = [*args[:2],*args[3:]]
        if len(args)==4 and args[:2]==["sed","-i"] and args[3]=="candidate/program.c" and args[2].startswith("s"):
            # GNU sed --sandbox rejects file/command operations. Supply the fixed path ourselves.
            result = self.env.execute({"command":shlex.join(["sed","--sandbox","-e",args[2],"candidate/program.c"])})
            if not result["returncode"] and self.write(result["output"]):
                return {"returncode":0,"output":"candidate/program.c saved. Next use: submit 'repair description'\n","exception_info":""}
            return denied
        if len(args)==3 and args[0]=="submit-line" and args[1].isascii() and args[1].isdigit() and len(args[1])<=5:
            original = (self.env.working_dir/"candidate/program.c").read_text(encoding="utf-8").splitlines(keepends=True)
            line = int(args[1])-1
            if 0<=line<len(original) and "\n" not in args[2] and public_text(args[2],4096).strip():
                replacement = args[2]+("\n" if original[line].endswith("\n") else "")
                if replacement!=original[line]:
                    original[line] = replacement
                    if self.write("".join(original)):
                        return self.submit("Replaced line "+str(line+1)+" in candidate/program.c.")
        if len(args)==4 and args[:3]==["printf","%s\\n",SENTINEL]:
            args = ["submit",args[3]]
        if len(args)==2 and args[0]=="submit" and any(row["operation"]=="write" for row in self.operations):
            note = args[1]
            if note.strip() and "\n" not in note:
                return self.submit(note)
        self.operations.append({"operation":"denied"})
        return denied


def prepare(env, packet):
    for tool in ("wc","sed"):
        env.config.wrapper_args += ["--ro-bind","/usr/bin/"+tool,"/bin/"+tool]
    work = env.working_dir
    os.chown(work,0,0)
    work.chmod(0o755)
    inputs = work/"inputs"
    inputs.mkdir()
    context = inputs/"repair-context.json"
    context.write_text(wire_text(packet),encoding="utf-8")
    context.chmod(0o444)
    inputs.chmod(0o555)
    output = work/"candidate"
    output.mkdir()
    os.chown(output,65534,65534)
    candidate = output/"program.c"
    candidate.write_text(packet["program.c"],encoding="utf-8")
    os.chown(candidate,65534,65534)
    test = env.execute({"command":
        'set -e; test "$(id -u)" = 65534; test ! -w .; test ! -w inputs/repair-context.json; '
        'test -w candidate/program.c; test ! -e /root/Deagle_incremental_execution; test ! -e /etc/shadow; '
        'test -z "$DEEPSEEK_API_KEY"; test "$(wc -l < /proc/net/route)" -eq 1; printf isolated'})
    if test["returncode"]!=0 or test["output"]!="isolated":
        raise ValueError("Sandbox preflight failed")
    return candidate
