"""Run the Light fixtures and isolated negative mapping/selection controls."""
import argparse,csv,json,subprocess,sys,tempfile
from pathlib import Path
S=Path(__file__).resolve().parents[2]/"scripts";sys.path.insert(0,str(S))
from d42_events import unchanged
from d42_prepare import select

def call(args,where=None,fail=False):
    result=subprocess.run(list(map(str,args)),cwd=where,capture_output=True,text=True)
    if (result.returncode!=0)!=fail:raise ValueError((args,result.stderr))
    return result.stdout if not fail else result.stderr

def main():
    p=argparse.ArgumentParser()
    for n in ("tools","test_tools","micro","out"):p.add_argument(n,type=Path)
    a=p.parse_args();d=a.out.resolve();d.mkdir(parents=True);summary={}
    summary["lifetime"]=call([a.test_tools/"lifetime42"],d)
    # Run every D4.1 conditional triplet on the independently linked D1 and full Audit trajectory.
    for spec in sorted(a.micro.rglob("spec")):
        if not (spec.parent/"oracle/native-learns.tsv").exists():continue
        root=d/("fixture-"+spec.parent.name);root.mkdir()
        light=root/"light.bin";full=root/"full.bin"
        call([a.test_tools/"native42",spec,light],root)
        call([a.test_tools/"triplet/native",spec,full],root)
        summary[spec.parent.name]=call([a.tools/"support-check",full,light])
        for delta in sorted(spec.parent.iterdir()):
            if not (delta/"decl").is_file() or not (delta/"spec").is_file():continue
            case_dir=root/delta.name;case_dir.mkdir()
            new_spec=(delta/"spec").read_text().splitlines()
            n0=int(spec.read_text().split()[0])+1;n1=int(new_spec[0].split()[0])+1
            manifest=case_dir/"new.tsv"
            with manifest.open("w") as f:
                for l in new_spec[1:]:
                    tag,*fields=l.split()
                    if tag in ("B","Q","U"):
                        print("C",tag,*(2*abs(int(v))+(int(v)<0) for v in fields),sep="\t",file=f)
            for label,archive in (("audit",full),("light",light)):
                dest=case_dir/label;dest.mkdir()
                call([a.tools/"select42",archive,delta/"model.tsv",manifest,delta/"variables.tsv",delta/"decl",dest,n0,n1,"semantic"])
            oracle=case_dir/"replay";oracle.mkdir()
            call([a.test_tools/"d4/check",full,delta/"inputs",delta/"map",spec.parent/"oracle/native-learns.tsv",delta/"decl",oracle])
            def content(path):return [r.split() for r in path.read_text().splitlines()]
            assert content(case_dir/"light/batch-rows.tsv")==content(case_dir/"audit/batch-rows.tsv")
            with (case_dir/"audit/catalog42.tsv").open() as f:native={r["native_id"]:r["ordinal"] for r in csv.DictReader(f,delimiter="\t")}
            expected=[[native[r[0]],*r[1:]] for r in content(oracle/"survivors.tsv")]
            assert expected==[[r[0],*r[3:]] for r in content(case_dir/"light/batch-rows.tsv")]
            summary[spec.parent.name+"/"+delta.name]=len(expected)
    case=S.parent/"bench/airline_reservations_6"
    lines=unchanged((case/"old/program.c").read_bytes(),(case/"candidate/program.c").read_bytes(),(case/"patch.diff").read_bytes())
    assert lines[4]==4 and 6 not in lines and 7 not in lines
    summary["deleted_second_lock"]="no source correspondence on removed lines 6 and 7"
    # Exercise the fixed ranking at its actual 512 cutoff, independent of any P1 run.
    q=d/"quality.tsv";(d/"batch-rows.tsv").write_text("".join(f"{n}\tB\t2\t2\t4\n" for n in range(1,521)))
    q.write_text("ordinal\tid\tlength\tlbd\tpropagations\tconflicts\tanalyze\tresident\n"+"".join(
        f"{i}\t{i}\t2\t{1+i%2}\t{i%5}\t0\t0\t1\n" for i in range(1,521)))
    sel=select(d,q,4,"top512");rows=list(csv.DictReader((d/"ranking.tsv").open(),delimiter="\t"))
    wanted=sorted(range(1,521),key=lambda i:(1+i%2,2,-(i%5),i))[:512]
    batch=[int(l.split()[0]) for l in (d/"selected.tmp").read_text().splitlines()[1:]]
    assert batch==sorted(wanted) and list(map(int,(r["ordinal"] for r in rows[:512])))==wanted
    summary["top512"]=sel
    (d/"results.json").write_text(json.dumps(summary,indent=2)+"\n")
if __name__=="__main__":main()
