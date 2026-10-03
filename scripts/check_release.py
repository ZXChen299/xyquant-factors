"""Validate exactly the files allowed into the public client repository."""
import ast
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
REMOTE_TOOLS={'list_factors','get_factor_info','preview_factor','create_export','get_export','list_exports',
              'list_strategies','get_strategy_info','get_strategy_performance','get_strategy_nav','get_research_team',
              'search_research','compare_strategies','get_research_updates'}
LOCAL_TOOLS={'get_connection_status','start_login','get_login_status','disconnect','download_export','get_download'}


def validate_tool_contract(root=None):
    """Check shipped declarations without importing code or accessing any login."""
    root=Path(root) if root is not None else ROOT
    tree=ast.parse((root/'client/factor_bridge.py').read_text(encoding='utf8'))
    tools={node.name for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
           and any(isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Attribute)
                   and isinstance(decorator.func.value,ast.Name) and decorator.func.value.id=='mcp'
                   and decorator.func.attr=='tool' for decorator in node.decorator_list)}
    if tools!=REMOTE_TOOLS|LOCAL_TOOLS:raise ValueError('Client tool declarations must match 20 expected tools (14 remote).')
    def declared_set(filename,name):
        nodes=ast.parse((root/'client'/filename).read_text(encoding='utf8')).body
        expression=next(node.value for node in nodes if isinstance(node,ast.Assign)
                        and any(isinstance(target,ast.Name) and target.id==name for target in node.targets))
        if not isinstance(expression,ast.Call) or not isinstance(expression.func,ast.Name) or expression.func.id!='frozenset':
            raise ValueError('Expected explicit safe tool allowlist.')
        return set(ast.literal_eval(expression.args[0]))
    if declared_set('remote.py','READ_TOOLS')!=REMOTE_TOOLS-{'create_export'}:
        raise ValueError('Read retries must cover all read tools and exclude export creation.')
    if declared_set('diagnostics.py','TOOLS')!=REMOTE_TOOLS|{'download_export'}:
        raise ValueError('Diagnostics tool allowlist differs from the shipped tools.')
    return dict(client_tools=len(tools),remote_tools=len(REMOTE_TOOLS))

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
    tools=validate_tool_contract()
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
    print(json.dumps({'checked_files':len(files),'runtime_sha256':digest,**tools,'publish_files':files},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
