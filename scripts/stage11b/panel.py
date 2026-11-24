"""Preselect every task with a numeric FM end-to-end time >= 10 s on either tool."""
from pathlib import Path
import csv,gzip,hashlib,io,json,shutil,sys,tarfile
import yaml
def sha(b):return hashlib.sha256(b).hexdigest()
def write(dst,obj):dst.write_bytes((json.dumps(obj,indent=2,sort_keys=True)+'\n').encode())
def select(work,out):
    public=work/'files/workspace';inventory=json.loads((work/'inventory.json').read_bytes())
    out.mkdir(exist_ok=True,parents=True)
    csv_names=['deagle.release.unwind2.15m.test.csv','zord-sc-solver.release.unwind2.15m.test.csv']
    tables=[]
    for n in csv_names:
        shutil.copyfile(public/n,out/n)
        rows=list(csv.DictReader((out/n).read_text().splitlines()));t={r['bench']:r['runtime'] for r in rows}
        assert len(rows)==len(t)==1063;tables.append(t)
    a,b=tables;assert a.keys()==b.keys()
    source={};specs={}
    for f in sorted((public/'benchmarks').glob('*/*.yml')):
        spec=yaml.safe_load(f.read_bytes());name=spec['input_files']
        k=f.parent.name+'.'+name[:-2]+'.smt'
        if k in a:
            if k in specs:raise ValueError('ambiguous artifact task '+k)
            specs[k]=(f,spec)
    assert specs.keys()==a.keys()
    def numeric(s):
        try:return float(s)
        except ValueError:return None
    def freeze(key,kind):
        f,s=specs[key];unit=f.parent/s['input_files']
        original=unit
        if kind=='weak-control':unit=public/'weak-sc-benchmarks'/('wsc.rewrite.i' if key=='pthread-theta.wsc.smt' else 'butterfly.i')
        source[key+'/'+unit.name]=unit.read_bytes();source[key+'/task.yml']=f.read_bytes()
        return dict(task=key,kind=kind,artifact_yaml=str(f.relative_to(public).as_posix()),yaml_sha256=sha(f.read_bytes()),
            original_yaml_input=original.name,original_sha256=sha(original.read_bytes()),unit=unit.name,source_sha256=sha(unit.read_bytes()),
            data_model=s['options']['data_model'],properties=s['properties'],deagle_raw=a[key],poct_raw=b[key],
            reach=any(x['property_file'].endswith('/unreach-call.prp') for x in s['properties']))
    rows=[freeze(k,'hard-single') for k in sorted(a) if max(numeric(a[k]) or 0,numeric(b[k]) or 0)>=10]
    assert len(rows)==13
    rows.extend(freeze(k,'weak-control') for k in ('pthread.butterfly.smt','pthread-theta.wsc.smt'))
    rows.append(freeze('pthread-deagle.arithmetic_prog_bad.smt','incomplete-control'))
    def pack():
        buf=io.BytesIO()
        with tarfile.open(fileobj=buf,mode='w') as tar:
            for n,data in sorted(source.items()):
                t=tarfile.TarInfo(n);t.size=len(data);tar.addfile(t,io.BytesIO(data))
        return gzip.compress(buf.getvalue(),mtime=0)
    (out/'inputs.tar.gz').write_bytes(pack())
    layers=[dict(layer=i,path=n,bytes=size) for i,n,size in inventory['entries'] if any(n.endswith('/'+c) or n.endswith('/.wh.'+c) for c in csv_names)]
    write(out/'selection.json',dict(doi='10.5281/zenodo.18616443',archive_md5='f21e9a4fed010781a240da865e488d77',image_sha256=inventory['image_sha256'],
        layers=layers,layer_paths=inventory['manifest']['Layers'],configuration_sha256=sha((public/'run-fm26.py').read_bytes()),
        tables={n:sha((out/n).read_bytes()) for n in csv_names},source_archive_sha256=sha((out/'inputs.tar.gz').read_bytes()),
        rule='All numeric >=10 s on Deagle OR Poct end-to-end; no verdict column; no result-based cutoff',rows=rows))
if __name__=='__main__':select(Path(sys.argv[1]),Path(sys.argv[2]))
