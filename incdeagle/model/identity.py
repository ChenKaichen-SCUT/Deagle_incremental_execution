"""Identities for the observed, bounded C/GOTO subset. All PCs are document-local."""
import hashlib
import json
import re
from collections import Counter, defaultdict
from functools import lru_cache


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|(?:0[xX][\da-fA-F]+|\d+)\w*|'
                   r'>>=|<<=|\+\+|--|->|<=|>=|==|!=|&&|\|\||[+\-*/%&|^]=|\S')


def shape(token):
    if token[0].isdigit() or token[0] in "\"'":
        return "<literal>"
    return {"<": "<rel-lt>", "<=": "<rel-lt>", ">": "<rel-gt>", ">=": "<rel-gt>"}.get(token, token)


def source_lines(path):
    if not path.is_file():
        return {}
    original = path.read_text(encoding="utf-8")
    # Keep physical line positions when removing comments. Only use this heuristic on
    # one-statement lines of our C harnesses; ambiguous lowering is rejected below.
    clean = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/',
                   lambda m: "\n" * m[0].count("\n") if m[0].startswith("/") else m[0], original)
    stack, result, previous = [], {}, []
    for number, line in enumerate(clean.splitlines(), 1):
        tokens = [shape(t) for t in TOKEN.findall(line)]
        while tokens[:1] == ["}"]:
            if stack:
                stack.pop()
            tokens = tokens[1:]
        result[str(number)] = (list(stack), tokens, tokens.count(";") > 1)
        for pos, token in enumerate(tokens):
            if token == "{":
                stack.append(tokens[:pos] or previous)
            elif token == "}" and stack:
                stack.pop()
        if tokens:
            previous = tokens
    return result


class GotoMap:
    def __init__(self, directory, document):
        self.rows = {}
        self.sources = {}
        self.local = {}
        self.loops = {}
        pool = document["ireps"]
        texts = {name: source_lines(directory / name) for name in ("program.c", "harness.c")}

        @lru_cache(None)
        def ir(index):
            if index is None:
                return None
            node = pool[index]
            tag = node["id"]
            op = {"lt": "lt-bound", "le": "lt-bound", "gt": "gt-bound", "ge": "gt-bound"}.get(tag, tag)
            named = {k: ir(v) for k, v in node.get("named", {}).items()
                     if k not in {"#source_location", "#end_location"}
                     and not (tag == "constant" and k in {"value", "#cformat"})}
            return [op, named, [ir(v) for v in node.get("sub", [])]]

        locations, instruction_counts, forced = defaultdict(set), Counter(), set()
        for row in document["instructions"]:
            fn, file, line, kind = (row[k] for k in ("function", "file", "line", "kind"))
            lowered = [ir(row.get("code")), ir(row.get("condition"))]
            if file in texts and line in texts[file]:
                block, tokens, complex_line = texts[file][line]
                descriptor = [file, fn, block, tokens]
            else:
                # Internal modeled-library instructions have no editable C snapshot.
                descriptor, complex_line = [file, fn, "native", kind, lowered], False
            src = digest(descriptor)
            ins = digest([src, kind, lowered])
            where = {"file": file, "line": line, "column": row["column"], "function": fn, "pc": row["pc"]}
            locations[src].add((file, line, row["column"]))
            instruction_counts[ins] += 1
            if complex_line:
                forced.add(src)
            self.sources.setdefault(src, {"descriptor": descriptor, "locations": []})["locations"].append(where)
            self.rows.setdefault(ins, {"source": src, "kind": kind, "locations": [], "targets": []})["locations"].append(where)
            self.local[(fn, row["pc"])] = (src, ins)
            if "local_loop" in row:
                self.loops[row["local_loop"]] = ins
        for src, info in self.sources.items():
            info["unique"] = len(locations[src]) == 1 and src not in forced
        for ins, info in self.rows.items():
            info["unique"] = self.sources[info["source"]]["unique"] and instruction_counts[ins] == 1
        for row in document["instructions"]:
            _, ins = self.lookup(row)
            self.rows[ins]["targets"].extend(self.local[(row["function"], t)][1] for t in row["targets"])

    def lookup(self, location):
        pair = self.local.get((location["function"], location["pc"]))
        if pair is None:
            missing = digest(["unresolved instruction", location["function"]])
            return missing, missing
        return pair

    def eligible(self, instruction):
        return self.rows.get(instruction, {}).get("unique", False)

    def export(self):
        return {"sources": self.sources, "instructions": self.rows}


def contexts(mapping, visits, births):
    threads = {0: ("entry", True)}
    births_per_site = Counter((b["parent"], mapping.lookup(b)[1]) for b in births)
    for b in births:
        _, ins = mapping.lookup(b)
        parent, valid = threads.get(b["parent"], ("missing-parent", False))
        threads[b["child"]] = (digest(["create", parent, ins]), valid and mapping.eligible(ins)
                                and births_per_site[b["parent"], ins] == 1)
    occurrences, result = Counter(), {}
    for index, visit in enumerate(visits, 1):
        tid, valid = threads.get(visit["thread"], ("missing-thread", False))
        stack = []
        for frame in visit["frames"]:
            caller = None
            if "caller" in frame:
                caller = mapping.lookup(frame["caller"])[1]
                valid = valid and mapping.eligible(caller)
            loop_counts = []
            for raw_loop, count in frame["loops"].items():
                back_edge = mapping.loops.get(raw_loop)
                valid = valid and mapping.eligible(back_edge)
                loop_counts.append([back_edge or "unknown-loop", count])
            loop_counts.sort()
            stack.append([frame["function"], caller, loop_counts])
        _, dispatch = mapping.lookup(visit)
        signature = (tid, digest(stack), dispatch)
        occurrences[signature] += 1
        result[index] = ({"thread": tid, "calls": stack, "dispatch": dispatch,
                          "occurrence": occurrences[signature]}, valid and mapping.eligible(dispatch))
    return threads, result


def step_identity(step, mapping, threads, visits):
    src, ins = mapping.lookup(step)
    thread, thread_ok = threads.get(step["thread"], ("missing-thread", False))
    context, ctx_ok = visits.get(step["visit"], ({"thread": thread, "calls": [], "dispatch": None,
                                                  "occurrence": None}, False))
    key = {"source": src, "instruction": ins, "thread": thread, "calls": context["calls"],
           "dispatch": context["dispatch"], "occurrence": context["occurrence"],
           "role": step["kind"], "object": step.get("object")}
    return key, thread_ok and ctx_ok and mapping.eligible(ins) and thread == context["thread"]
