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

def validate_manifest(metadata,binary):
    from build import source_digest,build_inputs,pe_machine,PYTHON_VERSION
    digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    source_version=re.search(r"^VERSION='([^']+)'",(ROOT/'client/auth_client.py').read_text(encoding='utf8'),re.M).group(1)
    plugin_version=json.loads((ROOT/'plugins/xyquant-factors/.codex-plugin/plugin.json').read_text(encoding='utf8'))['version']
    locked=dict(re.findall(r'^([\w.-]+)==([^\s\\]+)',(ROOT/'requirements-build.lock').read_text(encoding='utf8'),re.M))
    checks=[(digest==metadata.get('sha256')==binary.with_suffix('.exe.sha256').read_text().split()[0],'Runtime checksum mismatch.'),
            (metadata.get('version')==source_version==plugin_version,'Source, plugin and runtime versions differ.'),
            (metadata.get('build_dependencies')==locked,'Dependency provenance differs from lockfile.'),
            (binary.stat().st_size==metadata.get('bytes'),'Runtime size mismatch.'),
            (source_digest()==metadata.get('source_sha256'),'Client sources changed; rebuild the bundled executable.'),
            (metadata.get('python')==PYTHON_VERSION and metadata.get('pointer_bits')==64,'Pinned Python/x64 provenance missing.'),
            (metadata.get('pe_machine')==pe_machine(binary)=='AMD64','AMD64 executable required.'),
            (metadata.get('build_inputs')==build_inputs(),'Build inputs changed; rebuild the executable.'),
            (isinstance(metadata.get('source_commit'),str) and bool(re.fullmatch('[a-f0-9]{40}',metadata['source_commit'])),'Source commit missing.'),
            (type(metadata.get('source_dirty')) is bool,'Source working-tree provenance missing.'),
            (metadata.get('status')=='candidate' and metadata.get('signed') is False,'This workflow produces unsigned candidates only.')]
    failures=[message for passed,message in checks if not passed]
    if failures:raise ValueError('\n'.join(failures))
    return digest

def main():
    failures=[];files=[]
    for path,rel in release_files():
        if rel.parts[0] not in ALLOWED_ROOTS and rel.as_posix() not in ALLOWED_FILES:failures.append('Not allowlisted: '+rel.as_posix())
        if path.suffix.lower() in ('.pem','.key','.dpapi','.sqlite','.parquet','.csv','.zip','.xlsx','.xls','.p12','.pfx') or '.sqlite-' in path.name:failures.append('Private/data artifact: '+rel.as_posix())
        if path.is_symlink():failures.append('Symlink: '+rel.as_posix())
        data=path.read_bytes()
        if any(re.search(pattern,data) for pattern in SECRET_PATTERNS):failures.append('Credential marker: '+rel.as_posix())
        if path.suffix in ('.py','.json','.md','.toml','.yml','.yaml') and re.search(rb'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s"\']+',data):failures.append('Developer-specific path: '+rel.as_posix())
        files.append(rel.as_posix())
    plugin=ROOT/'plugins/xyquant-factors';binary=plugin/'bin/FactorBridge.exe'
    metadata=json.loads((plugin/'release.json').read_text(encoding='utf-8'))
    digest=validate_manifest(metadata,binary)
    if failures:raise SystemExit('\n'.join(failures))
    print(json.dumps({'checked_files':len(files),'runtime_sha256':digest,'publish_files':files},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
