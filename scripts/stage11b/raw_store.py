"""ZIP access for the release. Git-size chunks, if used, are byte-preserving."""
import contextlib,hashlib,json,tempfile,zipfile
from pathlib import Path

@contextlib.contextmanager
def archive(raw):
    raw=Path(raw)
    if (raw/'objects.zip').exists():
        with zipfile.ZipFile(raw/'objects.zip') as z:yield z
    else:
        parts=json.loads((raw/'parts.json').read_bytes())
        whole=hashlib.sha256()
        with tempfile.TemporaryFile() as f:
            for part in parts['parts']:
                blob=(raw/part['file']).read_bytes()
                if len(blob)!=part['bytes'] or hashlib.sha256(blob).hexdigest()!=part['sha256']:
                    raise ValueError('damaged raw archive part')
                f.write(blob);whole.update(blob)
            if whole.hexdigest()!=parts['sha256']:raise ValueError('damaged concatenation')
            f.seek(0)
            with zipfile.ZipFile(f) as z:yield z

def split(original,destination,limit=8*1024*1024):
    destination.mkdir(exist_ok=True,parents=True);h=hashlib.sha256();parts=[]
    with original.open('rb') as f:
        for i,data in enumerate(iter(lambda:f.read(limit),b''),1):
            name=f'objects-{i:03}.part'
            (destination/name).write_bytes(data);h.update(data)
            parts.append(dict(file=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    (destination/'parts.json').write_bytes((json.dumps(dict(sha256=h.hexdigest(),parts=parts),indent=2)+'\n').encode())
if __name__=='__main__':
    import sys
    if sys.argv[1]=='split':split(Path(sys.argv[2]),Path(sys.argv[3]))
    elif sys.argv[1]=='read':
        raw=Path(sys.argv[2]);files=json.loads((raw/'files.json').read_bytes())
        with archive(raw) as z:sys.stdout.buffer.write(z.read(files[sys.argv[3]]))
