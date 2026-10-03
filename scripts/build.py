"""Build an unsigned candidate with pinned Windows/Python inputs and provenance."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys
import shutil

ROOT=Path(__file__).resolve().parents[1]
PLUGIN=ROOT/'plugins'/'xyquant-factors'
PYTHON_VERSION='3.12.14'

def validate_runtime(os_name=None,version=None,pointer_bits=None,machine=None):
    os_name=os.name if os_name is None else os_name
    version=platform.python_version() if version is None else version
    pointer_bits=struct.calcsize('P')*8 if pointer_bits is None else pointer_bits
    machine=platform.machine() if machine is None else machine
    if os_name!='nt' or version!=PYTHON_VERSION or pointer_bits!=64 or machine.upper() not in ('AMD64','X86_64'):
        raise ValueError('Build requires Windows x64, a 64-bit interpreter, and Python '+PYTHON_VERSION+'.')
    return dict(python=version,pointer_bits=pointer_bits,machine=machine.upper())

def build_inputs():
    paths=list((ROOT/'client').glob('*.py'))+list((ROOT/'scripts').glob('*.py'))
    paths+=list((ROOT/'.github/workflows').glob('*.yml'))+[ROOT/'requirements-build.lock']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}

def validate_dependencies():
    text=(ROOT/'requirements-build.lock').read_text(encoding='utf8')
    requirements=re.findall(r'^([\w.-]+)==([^\s\\]+)',text,re.M)
    if not requirements or '--hash=sha256:' not in text:raise ValueError('A hash-locked dependency set is required.')
    installed={}
    for name,expected in requirements:
        actual=importlib.metadata.version(name)
        if actual!=expected:raise ValueError('Build dependency version mismatch: '+name)
        installed[name]=actual
    return installed

def git_provenance():
    try:
        def git(*args):
            return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'-C',str(ROOT),*args],stderr=subprocess.DEVNULL,timeout=15).decode().strip()
        commit=git('rev-parse','HEAD')
        if not re.fullmatch(r'[a-f0-9]{40}',commit):raise ValueError()
        return dict(commit=commit,dirty=bool(git('status','--porcelain')))
    except (OSError,ValueError,subprocess.SubprocessError):
        raise ValueError('Build must run inside a Git checkout to record its source commit.') from None

def pe_machine(binary):
    with Path(binary).open('rb') as stream:
        if stream.read(2)!=b'MZ':raise ValueError('Invalid Windows executable.')
        stream.seek(0x3c);offset=struct.unpack('<I',stream.read(4))[0];stream.seek(offset)
        if stream.read(4)!=b'PE\0\0':raise ValueError('Invalid PE signature.')
        machine=struct.unpack('<H',stream.read(2))[0]
    if machine!=0x8664:raise ValueError('Executable is not AMD64.')
    return 'AMD64'

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
    runtime=validate_runtime();dependencies=validate_dependencies();provenance=git_provenance();inputs=build_inputs()
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
    binary=target/'FactorBridge.exe';architecture=pe_machine(binary);digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    binary.with_suffix('.exe.sha256').write_bytes((digest+'  FactorBridge.exe\n').encode('ascii'))
    manifest=dict(version=VERSION,platform='windows-x64',python=runtime['python'],pointer_bits=runtime['pointer_bits'],
                  pe_machine=architecture,signed=False,bytes=binary.stat().st_size,sha256=digest,
                  source_sha256=source_digest(),source_commit=provenance['commit'],source_dirty=provenance['dirty'],
                  build_inputs=inputs,build_dependencies=dependencies,status='candidate')
    (PLUGIN/'release.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode('utf8'))
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('build_inputs','build_dependencies')}),flush=True)

if __name__=='__main__':main()
