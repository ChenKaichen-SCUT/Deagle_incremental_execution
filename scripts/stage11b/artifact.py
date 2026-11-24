"""Read the published image as data, without loading the Docker image or running its tools."""
from pathlib import Path,PurePosixPath
import argparse,csv,hashlib,io,json,shutil,tarfile,zipfile

def inspect_image(archive,work):
    work.mkdir(exist_ok=True,parents=True)
    image=work/'poct-fm26.tar'
    if not image.exists():
        with zipfile.ZipFile(archive) as z,z.open('paper168-artifact/poct-fm26.tar') as src,image.open('wb') as out:
            shutil.copyfileobj(src,out,1024*1024)
    h=hashlib.sha256()
    with image.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    if h.hexdigest()!='e0984b7ccf8b1b570ba2ccb80b6340d43b4ede39e1f148462bcc5c7c1b675fe2':raise ValueError('image checksum')
    out=work/'files';out.mkdir(exist_ok=True)
    entries=[]; tasks=[]; data=[]
    with tarfile.open(image,'r:') as docker:
        manifest=json.load(docker.extractfile('manifest.json'))[0]
        for ix,layer in enumerate(manifest['Layers']):
            with tarfile.open(fileobj=docker.extractfile(layer),mode='r|*') as t:
                for m in t:
                    p=PurePosixPath(m.name.lstrip('./'))
                    if not m.isfile() or '..' in p.parts:continue
                    if not p.parts or p.parts[0]!='workspace':continue
                    parts=p.parts[1:]
                    if not parts:continue
                    if len(parts)==1 or p.suffix in ('.csv','.xlsx','.xml','.bz2') or any('result' in k.lower() for k in parts[:-1]):
                        entries.append([ix,str(p),m.size])
                    # Keep all raw task SOURCES locally for subsequent prespecified selection only.
                    if parts[0] in ('benchmarks','weak-sc-benchmarks') and p.suffix in ('.i','.c','.yml','.prp'):
                        tasks.append(str(p))
                    elif not (len(parts)==1 and p.suffix in ('.py','.csv','.txt','.prp','.md','.sh') or p.suffix in ('.csv','.xlsx') or p.name in ('Dockerfile','unreach-call.prp')):continue
                    if m.size>50*1024*1024:continue
                    filename=out.joinpath(*p.parts)
                    filename.parent.mkdir(parents=True,exist_ok=True)
                    blob=t.extractfile(m).read();filename.write_bytes(blob)
                    if p.suffix=='.csv':data.append([str(p),hashlib.sha256(blob).hexdigest(),len(blob.splitlines())])
            print('read layer',ix,flush=True)
    (work/'inventory.json').write_text(json.dumps(dict(image_sha256=h.hexdigest(),manifest=manifest,entries=entries,tasks=sorted(set(tasks)),tables=data),indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('work',type=Path)
    a=p.parse_args();inspect_image(a.archive,a.work)
