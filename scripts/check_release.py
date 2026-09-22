"""Validate exactly the files allowed into the public client repository."""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
ALLOWED_ROOTS={'client','plugins','scripts','docs','.agents','.github'}
ALLOWED_FILES={'README.md','LICENSE','CHANGELOG.md','.gitignore','.gitattributes','requirements-build.lock','THIRD_PARTY_NOTICES.md'}
SKIP_PARTS={'.git','.work','__pycache__'}
SECRET_PATTERNS=[rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',rb'gh[pousr]_[A-Za-z0-9]{30,}',rb'github_pat_[A-Za-z0-9_]{30,}']

def release_files():
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if any(part in SKIP_PARTS for part in rel.parts) or not path.is_file():continue
        yield path,rel

def main():
    failures=[];files=[]
    for path,rel in release_files():
        if rel.parts[0] not in ALLOWED_ROOTS and rel.as_posix() not in ALLOWED_FILES:failures.append('Not allowlisted: '+rel.as_posix())
        if path.suffix.lower() in ('.pem','.key','.dpapi','.sqlite','.parquet','.csv','.zip') or '.sqlite-' in path.name:failures.append('Private/data artifact: '+rel.as_posix())
        if path.is_symlink():failures.append('Symlink: '+rel.as_posix())
        data=path.read_bytes()
        if any(re.search(pattern,data) for pattern in SECRET_PATTERNS):failures.append('Credential marker: '+rel.as_posix())
        if path.suffix in ('.py','.json','.md','.toml','.yml','.yaml') and re.search(rb'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s"\']+',data):failures.append('Developer-specific path: '+rel.as_posix())
        files.append(rel.as_posix())
    plugin=ROOT/'plugins/xyquant-factors';binary=plugin/'bin/FactorBridge.exe'
    metadata=json.loads((plugin/'release.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest==metadata['sha256']==binary.with_suffix('.exe.sha256').read_text().split()[0]
    assert binary.stat().st_size==metadata['bytes']
    from build import source_digest
    assert source_digest()==metadata['source_sha256'],'Client sources changed; rebuild the bundled executable.'
    if failures:raise SystemExit('\n'.join(failures))
    print(json.dumps({'checked_files':len(files),'runtime_sha256':digest,'publish_files':files},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
