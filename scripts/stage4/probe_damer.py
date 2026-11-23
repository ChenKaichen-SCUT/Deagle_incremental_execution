"""Run upstream DAMER AST matching on the batch function and a small edit corpus."""
import argparse
import json
import shlex
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--out",type=Path,required=True);d=cli.parse_args().out.resolve()
    d.mkdir(parents=True,exist_ok=False)
    src=ROOT/"third_party/damer-camc"
    build=src/"build"
    flags=(build/"CMakeFiles/PDNet2_0.dir/flags.make").read_text().splitlines()
    options=[arg for key in ("CXX_DEFINES","CXX_INCLUDES","CXX_FLAGS") for row in flags if row.startswith(key+" =")
             for arg in shlex.split(row.split("=",1)[1])]
    obj=d/"probe.o";exe=d/"probe"
    compile_cmd=["g++",*options,"-I",str(src),"-c",str(ROOT/"scripts/stage4/damer_probe.cpp"),"-o",str(obj)]
    subprocess.run(compile_cmd,cwd=build,check=True)
    link=shlex.split((build/"CMakeFiles/PDNet2_0.dir/link.txt").read_text())
    i=next(i for i,s in enumerate(link) if s.endswith("/main.cpp.o"));link[i]=str(obj);link[link.index("-o")+1]=str(exe)
    subprocess.run(link,cwd=build,check=True)
    old=(ROOT/"cases/batch_total/old/program.c").read_text()
    candidate=(ROOT/"cases/batch_total/candidate/program.c").read_text()
    prefix="int shipped_units;\n"
    sample="int a,b,c;\nint main(){\na=1;\nb=2;\nc=3;\nreturn 0;\n}\n"
    pairs={"batch_total":(prefix+old,prefix+candidate),"insert":(sample,sample.replace("b=2;","a=4;\nb=2;")),
           "delete":(sample,sample.replace("b=2;\n","")),"move":(sample,sample.replace("a=1;\nb=2;","b=2;\na=1;"))}
    report={"commit":subprocess.check_output(["git","-C",src,"rev-parse","HEAD"],text=True).strip(),
            "compile":compile_cmd,"link":link,"pairs":{}}
    for name,versions in pairs.items():
        folder=d/name;folder.mkdir()
        files=[folder/f for f in ("old.c","candidate.c")]
        for file,code in zip(files,versions):file.write_text(code)
        run=subprocess.run([exe,*files],cwd=folder,timeout=30,capture_output=True)
        (folder/"stdout").write_bytes(run.stdout);(folder/"stderr").write_bytes(run.stderr)
        lines=run.stdout.decode(errors="replace").splitlines()
        report["pairs"][name]={"exit":run.returncode,"rows":[line for line in lines if line.split() and
                   line.split()[0] in {"matches","statement","changed_blocks","block","modify","add","delete","move"}]}
    (d/"probe.json").write_text(json.dumps(report,indent=2)+"\n")
    print({k:(v["exit"],[x for x in v["rows"] if x.split()[0]!="statement"]) for k,v in report["pairs"].items()})


if __name__=="__main__":main()
