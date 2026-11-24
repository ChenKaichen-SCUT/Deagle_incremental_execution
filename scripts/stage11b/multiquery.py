"""Record both arithmetic versions through stock native multi-query solving."""
import hashlib,json,shutil,sys
from pathlib import Path
from singles import execute,record
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/svcomp26'))
from stream import inspect,states
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main(run,pilot,work):
    case=pilot/'cases/svcomp26';exe=run/'native/src/cbmc/deagle_exe'
    for name,src in [('P0',case/'c/pthread-deagle/arithmetic_prog_bad.i'),('P1',case/'versions/arithmetic_prog_bad/P1/program.i')]:
        temp=work/name;temp.mkdir(exist_ok=True,parents=True)
        dest=run/'controls/multiquery'/name;dest.mkdir(exist_ok=True,parents=True)
        shutil.copyfile(src,temp/'program.i')
        row=execute(temp,exe,'program.i',['--function','main','--deagle-closure','--mm','sc','--32','--unwind','5','--unwinding-assertions'],180,
            {'S8_OUT':str(temp),'S8_STREAM':'1','S10_DIR':str(temp)})
        stream,_=inspect(temp/'s8-input.bin')
        assert len(stream['queries'])>1 and row['classification']=='INCOMPLETE_UNWINDING'
        row.update(stream=stream,source_sha256=sha(src),stream_sha256=sha(temp/'s8-input.bin'),disposition='stock multi-query only; incomplete unrolling; no repair success')
        record(dest/'receipt.json',row)
        for n in ('output.json.gz','stdout.gz','stderr.gz','native-state.tsv','boundary.tsv','s8-graph.tsv'):
            if (temp/n).is_file():shutil.copyfile(temp/n,dest/n)
if __name__=='__main__':main(*[Path(a).resolve() for a in sys.argv[1:]])
