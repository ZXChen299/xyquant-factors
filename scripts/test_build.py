import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import build
import check_release


class BuildTests(unittest.TestCase):
    def test_shipped_tool_and_safe_read_allowlists_match_contract(self):
        self.assertEqual(check_release.validate_tool_contract(),dict(client_tools=20,remote_tools=14))

    def test_release_rejects_missing_tool_or_mutating_retry_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'client').mkdir()
            for name in ('factor_bridge.py','remote.py','diagnostics.py'):
                (root/'client'/name).write_bytes((check_release.ROOT/'client'/name).read_bytes())
            remote_path=root/'client/remote.py';original=remote_path.read_text(encoding='utf8')
            remote_path.write_text(original.replace("READ_TOOLS = frozenset((", "READ_TOOLS = frozenset(('create_export', ",1),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'exclude export creation'):check_release.validate_tool_contract(root)
            remote_path.write_text(original,encoding='utf8')
            bridge=root/'client/factor_bridge.py';text=bridge.read_text(encoding='utf8')
            bridge.write_text(text.replace('async def search_research(', 'async def accidental_other_name(',1),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'20 expected tools'):check_release.validate_tool_contract(root)

    def test_runtime_rejects_32bit_arm_and_unpinned_python(self):
        good=dict(os_name='nt',version='3.12.14',pointer_bits=64,machine='AMD64')
        self.assertEqual(build.validate_runtime(**good)['pointer_bits'],64)
        for change in ({'pointer_bits':32},{'machine':'ARM64'},{'version':'3.12.13'},{'os_name':'posix'}):
            with self.subTest(change=change),self.assertRaises(ValueError):build.validate_runtime(**dict(good,**change))

    def test_pe_header_must_be_actual_amd64(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'candidate.exe'
            payload=bytearray(128);payload[:2]=b'MZ';struct.pack_into('<I',payload,0x3c,64);payload[64:68]=b'PE\0\0'
            struct.pack_into('<H',payload,68,0x14c);path.write_bytes(payload)
            with self.assertRaises(ValueError):build.pe_machine(path)
            struct.pack_into('<H',payload,68,0x8664);path.write_bytes(payload)
            self.assertEqual(build.pe_machine(path),'AMD64')

    def test_lock_matches_versions_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as td,patch.object(build,'ROOT',Path(td)):
            (Path(td)/'requirements-build.lock').write_text('sample==1.2.3 \\\n    --hash=sha256:'+'a'*64+'\n')
            with patch.object(build.importlib.metadata,'version',return_value='1.2.3'):
                self.assertEqual(build.validate_dependencies(),{'sample':'1.2.3'})
            with patch.object(build.importlib.metadata,'version',return_value='1.2.4'),self.assertRaises(ValueError):build.validate_dependencies()

    def test_source_and_build_inputs_detect_stale_binary_without_assert(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'candidate.exe';path.write_bytes(b'fixture')
            digest=hashlib.sha256(path.read_bytes()).hexdigest();path.with_suffix('.exe.sha256').write_text(digest+'  candidate.exe')
            metadata=dict(sha256=digest,bytes=7,source_sha256='old',python='3.12.14',pointer_bits=64,pe_machine='AMD64',
                          build_inputs={'old':'hash'},source_commit='a'*40,source_dirty=False,status='candidate',signed=False)
            with patch.object(build,'pe_machine',return_value='AMD64'),patch.object(build,'source_digest',return_value='new'),patch.object(build,'build_inputs',return_value={'new':'hash'}):
                with self.assertRaisesRegex(ValueError,'Client sources changed'):check_release.validate_manifest(metadata,path)


if __name__=='__main__':unittest.main()
