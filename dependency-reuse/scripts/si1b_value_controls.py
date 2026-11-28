"""Fault the archived first-root envelope or batch. No Deagle process or SAT query is started."""
import argparse
import importlib.util
from pathlib import Path
import shutil

from si1b_review_space import BASE,EVIDENCE,check,digest,read,save
from si1b_value_boundary import expected_args


def controls(droot,work,output):
    code=BASE/"diagnostics/si1b-value/d43_prepare.py"
    module=importlib.util.spec_from_file_location("value_worker_control",code)
    worker=importlib.util.module_from_spec(module);module.loader.exec_module(worker)
    case="fib_updates_8";fr=EVIDENCE/"si1b-value/frozen"
    work.mkdir(parents=True)
    lib=work/"library";shutil.copytree(fr/case,lib)
    seal=read(lib/"seal.json");sha=read(fr/"batches.json")["seals"][case]
    old=droot/"matrix"/case/"compact-reuse/P1"
    cwd=Path(read(old/"run.json")["cwd"])
    # Archived boundary embeds its original work directory. For a restore-only host,
    # reconstruct the staged files in scratch and canonically relocate only the nested SITE41 directory field.
    scratch_cwd=work/"staged-inputs";shutil.copytree(old/"work",scratch_cwd)
    from d43_owner_probe import canonical_site
    def relocate(field,prev,now):
        if prev not in field:return field
        if field==prev:return now
        blocks=[];i=0
        while i<len(field):
            colon=field.index(b":",i);n=int(field[i:colon]);start=colon+1;sub=relocate(field[start:start+n],prev,now)
            blocks.append(str(len(sub)).encode()+b":"+sub);i=start+n
        return b"".join(blocks)
    data=[]
    for line in (old/"native/boundary.tsv").read_bytes().splitlines(keepends=True):
        if line.startswith(b"SITE41\t"):
            t,i,field=line[:-1].split(b"\t")
            target=relocate(field,str(cwd).encode(),str(scratch_cwd).encode())
            check(canonical_site(field,str(cwd).encode())==canonical_site(target,str(scratch_cwd).encode()),"invalid relocation")
            line=b"\t".join((t,i,target))+b"\n"
        data.append(line)
    faults={"B_content":b"C\tB\t","Q_content":b"C\tQ\t","native_gate":b"G\t","RF_binding":b"EDGE\trf\t",
            "Guard_binding":b"GUARD\t","variable_count":b"N\t","missing_READY":b"READY\t"}
    results={}
    for label in ("positive",*faults,"batch_literal","batch_truncated","seal_tampered","ABI_flags","wrong_ELF","source","wrong_arm"):
        dest=work/label;dest.mkdir()
        altered=data.copy()
        if label in faults:
            j=next(j for j,l in enumerate(altered) if l.startswith(faults[label]))
            fields=altered[j].strip().split(b"\t")
            if label=="missing_READY":altered.pop(j)
            else:
                index=4 if label=="RF_binding" else -1
                fields[index]=str(int(fields[index])^1).encode()
                altered[j]=b"\t".join(fields)+b"\n"
        (dest/"boundary.tsv").write_bytes(b"".join(altered))
        raw=(fr/case/"new.ready.tsv").read_bytes()
        payload=raw
        if label=="batch_truncated":payload=raw[:-8]
        if label=="batch_literal":
            lines=raw.splitlines();fields=lines[1].split(b"\t");fields[-1]=str(int(fields[-1])^1).encode()
            lines[1]=b"\t".join(fields);payload=b"\n".join(lines)+b"\n"
        (lib/"new.ready.tsv").write_bytes(payload)
        shutil.copyfile(fr/case/"seal.json",lib/"seal.json")
        if label=="seal_tampered":
            with (lib/"seal.json").open("ab") as f:f.write(b" ")
        name=next(iter(seal["inputs"]))
        shutil.copyfile(old/"work"/name,scratch_cwd/name)
        if label=="source":
            with (scratch_cwd/name).open("ab") as f:f.write(b"\n")
        arm="other" if label=="wrong_arm" else "new"
        ctl=dict(format=seal["format"],case=case,arm=arm)
        argv=expected_args(lib,dest,code.parent,"new",seal["argv"])
        if label=="ABI_flags":argv[argv.index("--64")]="--32"
        error=None
        try:
            worker.publish(lib,dest,code.parent,ctl,scratch_cwd,argv,"wrong" if label=="wrong_ELF" else seal["native_elf"],sha)
        except ValueError as exc:error=str(exc)
        accepted=(dest/"ready.tsv").exists()
        check(accepted==(error is None)==(label=="positive"),"fault control "+label)
        if accepted:check((dest/"ready.tsv").read_bytes()==raw,"positive payload")
        results[label]=dict(published=accepted,rejection=error)
    save(output,results)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for arg in ("D","work","output"):p.add_argument(arg,type=Path)
    a=p.parse_args();controls(a.D,a.work,a.output)
