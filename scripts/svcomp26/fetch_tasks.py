"""Fetch directories from the pinned GitLab revision and original per-task logfiles from SV-COMP."""
import argparse
import bz2
import concurrent.futures
import io
import tarfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path,PurePosixPath
from collect import API,SITE,get,hashb,dump,rel
from config import TAG,TASKS

def run(cache,e):
    raw=e/'official';names=set();logs={}
    for p in sorted(raw.glob('deagle.*.Concurrency.xml.bz2')):
        doc=ET.fromstring(bz2.decompress(p.read_bytes()))
        for row in doc.findall('run'):
            name=rel(row.get('name'));names.add(name.split('/')[0])
            for n in row.get('files').strip('[]').split(','):names.add(rel(n.strip()).split('/')[0])
            task=PurePosixPath(name).stem;category=doc.get('block')
            if task in TASKS and name==TASKS[task][0]+'/'+task+'.yml' and category==('C.no-data-race.Concurrency' if task=='workstealqueue_mutex-1' else 'C.unreach-call.Concurrency'):
                prefix=p.name.split('.results.')[0];target='SV-COMP26_'+category.split('.')[1]+'.'+task+'.yml.log'
                logs[target]=SITE+prefix+'.logfiles/'+target
    names.add('properties')
    def directory(name):
        archive=cache/(name+'.tgz');url=API+'archive.tar.gz?'+urllib.parse.urlencode({'sha':TAG,'path':'c/'+name})
        if not archive.exists():archive.write_bytes(get(url))
        b=archive.read_bytes();cnt=0
        with tarfile.open(fileobj=io.BytesIO(b)) as t:
            for member in t:
                m=PurePosixPath(member.name)
                if m.is_absolute() or '..' in m.parts or '\\' in member.name:raise ValueError(member.name)
                if not member.isfile() or m.parts[1:3]!=('c',name):continue
                if TAG not in m.parts[0]:raise ValueError('archive revision not pinned')
                dest=cache/'bench'/Path(*m.parts[1:]);dest.parent.mkdir(parents=True,exist_ok=True)
                blob=t.extractfile(member).read()
                if not dest.is_file() or dest.read_bytes()!=blob:dest.write_bytes(blob)
                cnt+=1
        if not cnt:raise ValueError(name)
        return name,dict(url=url,archive_sha256=hashb(b),files=cnt)
    with concurrent.futures.ThreadPoolExecutor(3) as pool:dirs=dict(pool.map(directory,sorted(names)))
    dump(e/'directory-downloads.json',dirs)
    logdir=raw/'logs';logdir.mkdir(exist_ok=True);receipts={}
    zipname=next(iter(logs.values())).rsplit('/',1)[0]+'.zip'
    archivefile=raw/'deagle-logfiles.zip'
    if not archivefile.exists():archivefile.write_bytes(get(zipname))
    receipts['archive']=dict(url=zipname,sha256=hashb(archivefile.read_bytes()))
    def logfile(z,item):
        name,url=item
        p=logdir/name
        members=[m for m in z.namelist() if m.endswith('/'+name)]
        if len(members)!=1:raise ValueError((name,members))
        data=z.read(members[0])
        if p.exists() and p.read_bytes()!=data:raise ValueError('loose file disagrees with official archive')
        p.write_bytes(data)
        if b'deagle' not in p.read_bytes().lower():raise ValueError(name)
        return name,dict(url=url,archive_member=members[0],sha256=hashb(p.read_bytes()))
    with zipfile.ZipFile(archivefile) as z:receipts.update(dict(logfile(z,item) for item in sorted(logs.items())))
    dump(e/'official-log-sources.json',receipts)
    print(len(dirs),'pinned directories and',len(logs),'official logs')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('cache',type=Path);p.add_argument('evidence',type=Path);a=p.parse_args();run(a.cache,a.evidence)
