"""Freeze the existing five pairs and the two explicitly bounded benchmark adaptations."""
import difflib
import json
import shutil
import tarfile
from pathlib import Path

import yaml

from incdeagle.model.identity import file_sha, read, save
from incdeagle.repair import PROTECTED, apply_source_patch, inspect

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE6 = ROOT/"reports/evidence/stage-06"
SMALL = {
    "batch_total": ("ai-single-edit","stage6_mini_deepseek","constant"),
    "threshold_guard": ("replay-threshold_guard","stage2_manual","guard"),
    "split_counter": ("replay-split_counter","stage2_mini_deepseek","synchronization"),
    "partial_counter": ("replay-partial_counter","stage3_manual","partial_synchronization"),
    "batch_retained": ("manual-retained","stage6_manual","constant_retained_error"),
}
LARGE = ("fib_updates","airline_reservations","fib_updates_8","airline_reservations_6")


def expanded_case(case):
    fixture = ROOT/"tests/stage7"/case.name
    spec = read(fixture/"spec.json")
    template_dir=fixture.parent/spec["template"] if "template" in spec else fixture
    for name in ("harness.c","old/program.c","candidate/program.c"):
        dst = case/name
        dst.parent.mkdir(exist_ok=True,parents=True)
        shutil.copyfile(template_dir/name,dst)
    if "harness_replacements" in spec:
        harness=case/"harness.c"
        text=harness.read_text()
        for old,new,count in spec["harness_replacements"]:
            if text.count(old)!=count:raise ValueError("Scaled workload template changed")
            text=text.replace(old,new)
        harness.write_text(text,encoding="utf-8")
    template = ROOT/"cases/batch_total"
    gamma,phi = read(template/"gamma.json"),read(template/"phi.json")
    task = yaml.safe_load((template/"task.yaml").read_bytes())
    lines = (case/"harness.c").read_text().splitlines()
    assertions = [(n,line.strip()) for n,line in enumerate(lines,1) if line.strip().startswith("assert(")]
    if len(assertions)!=1:
        raise ValueError("Expected a single protected target")
    from hashlib import sha256
    line,statement = assertions[0]
    phi.update(assertion=statement,description=spec["property"],assertion_sha256=sha256(statement.encode()).hexdigest(),
               source={"file":"harness.c","function":"main","line":line})
    sem = gamma["semantics"]
    sem.update(unwind=spec["unwind"],worker_threads=spec["workers"],thread_bound=spec["thread_bound"],
               assumptions=spec["assumptions"])
    gamma["source_argv"][gamma["source_argv"].index("--unwind")+1]=str(sem["unwind"])
    gamma["harness_sha256"]=file_sha(case/"harness.c")
    task.update(case_id=case.name,source_origin=spec["origin"],semantics=sem)
    task["property"].update(description=phi["description"],original_assertion_fingerprint=phi["assertion_sha256"])
    task["repair"].update(method="stage7_manual",change_type=spec["patch_type"],intent=spec["intent"])
    save(case/"phi.json",phi)
    save(case/"gamma.json",gamma)
    (case/"task.yaml").write_text(yaml.safe_dump(task,sort_keys=False),encoding="utf-8")
    return "stage7_manual",spec["patch_type"]


def prepare(out, group):
    matrix_path=out/"matrix.json"
    matrix=read(matrix_path) if matrix_path.exists() else {}
    names=list(SMALL) if group=="existing" else list(LARGE)
    acceptance=read(EVIDENCE6/"acceptance.json")["runs"]
    for name in names:
        if name in matrix:
            validate(out,matrix[name])
            continue
        if name in SMALL:
            role,origin,kind=SMALL[name]
            prior=acceptance[role]
            case_name=prior["case"]
            original=ROOT/("tests/stage3" if case_name=="partial_counter" else "cases")/case_name
            case=out/"sources"/name/case_name
            for file in PROTECTED:
                dst=case/file
                dst.parent.mkdir(exist_ok=True,parents=True)
                shutil.copyfile(original/file,dst)
            with tarfile.open(EVIDENCE6/"full-runs.tar.gz","r:gz") as archive:
                prefix="verification/"+role+"/"
                candidate=archive.extractfile(prefix+"snapshot/"+case_name+"/candidate/program.c").read()
                archived=archive.extractfile(prefix+"repair/patch.diff").read()
            (case/"candidate").mkdir()
            (case/"candidate/program.c").write_bytes(candidate)
            (case/"patch.diff").write_bytes(archived)
            if (file_sha(case/"candidate/program.c")!=prior["candidate_sha256"] or
                    file_sha(case/"old/program.c")!=prior["old_source_sha256"] or
                    file_sha(case/"gamma.json")!=prior["gamma_sha256"] or file_sha(case/"phi.json")!=prior["phi_sha256"]):
                raise ValueError("Frozen Stage 6 pair changed")
        else:
            case=out/"sources"/name/name
            origin,kind=expanded_case(case)
            old=(case/"old/program.c").read_text().splitlines(True)
            new=(case/"candidate/program.c").read_text().splitlines(True)
            (case/"patch.diff").write_text("".join(difflib.unified_diff(old,new,fromfile="a/program.c",tofile="b/program.c")))
            role=None
        snap={f:file_sha(case/f) for f in (*PROTECTED,"candidate/program.c","patch.diff")}
        save(case/"freeze.json",{"files_sha256":snap})
        item={"case_id":name,"case_dir":case.relative_to(out).as_posix(),"patch_origin":origin,"patch_type":kind,
              "stage6_run":role,"files":snap}
        validate(out,item)
        matrix[name]=item
    save(matrix_path,matrix)
    return names


def validate(out,item):
    case=out/item["case_dir"]
    if any(file_sha(case/key)!=value for key,value in item["files"].items()):
        raise ValueError("Experiment snapshot differs from the source lock")
    inspect(case)
    if apply_source_patch((case/"old/program.c").read_bytes(),(case/"patch.diff").read_bytes())!=(case/"candidate/program.c").read_bytes():
        raise ValueError("Frozen patch does not reproduce the frozen P1")
    return case
