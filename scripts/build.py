"""Build the self-contained Windows plugin runtime with the active Python 3.12."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'plugins'/'xyquant-factors'

def source_digest():
    digest=hashlib.sha256()
    files=sorted((ROOT/'client').glob('*.py'))+[ROOT/'requirements-build.lock']
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()

def copy_notices():
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT/name,PLUGIN/name)
    shutil.copytree(ROOT/'docs/licenses',PLUGIN/'docs/licenses',dirs_exist_ok=True)

def main():
    if os.name!='nt' or sys.version_info[:2]!=(3,12):raise SystemExit('Build requires Windows x64 and Python 3.12.')
    sys.path.insert(0,str(ROOT/'client'))
    from auth_client import VERSION
    copy_notices()
    output=ROOT/'.work/build';output.mkdir(parents=True,exist_ok=True)
    target=PLUGIN/'bin';target.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--name','FactorBridge',
             '--distpath',str(target),'--workpath',str(output/'work'),'--specpath',str(output),
             '--paths',str(ROOT/'client'),'--collect-submodules','mcp.server','--collect-submodules','mcp.client',
             '--collect-data','mcp_types','--copy-metadata','mcp','--copy-metadata','mcp-types',str(ROOT/'client/factor_bridge.py')]
    with (output/'build.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=target/'FactorBridge.exe';digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    binary.with_suffix('.exe.sha256').write_text(digest+'  FactorBridge.exe\n',encoding='ascii')
    manifest=dict(version=VERSION,platform='windows-x64',python='3.12',signed=False,bytes=binary.stat().st_size,
                  sha256=digest,source_sha256=source_digest(),status='candidate')
    (PLUGIN/'release.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest),flush=True)

if __name__=='__main__':main()
