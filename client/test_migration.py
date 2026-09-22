import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import tomlkit
from auth_client import ClientError, ORIGIN
from configuration import migrate_legacy


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.config=self.root/'codex'/'config.toml'
        self.config.parent.mkdir()
        self.state=self.root/'FactorConnect'
        self.state.mkdir()
        (self.state/'credentials.dpapi').write_bytes(b'encrypted-fixture')
        (self.state/'downloads.sqlite').write_bytes(b'fixture-download-records')
        self.patches=contextlib.ExitStack()
        self.patches.enter_context(patch('configuration.app_dir',return_value=self.state))
        self.patches.enter_context(patch('configuration.mutex',side_effect=lambda *a,**k:contextlib.nullcontext()))
        self.addCleanup(self.patches.close)
        self.addCleanup(self.temp.cleanup)

    def seed(self,entry):
        doc=tomlkit.parse('# retain comment\nmodel="unchanged"\n[mcp_servers.other]\ncommand="another-service"\n[plugins."another@market"]\nenabled=true\n')
        doc['mcp_servers']['xyquant_factors']=entry
        self.config.write_bytes(tomlkit.dumps(doc).replace('\n','\r\n').encode('utf-8'))
        return self.config.read_bytes()

    def test_remote_migration_exact_backup_preserves_other_settings_and_state(self):
        original=self.seed({'url':ORIGIN+'/mcp','http_headers':{'Authorization':'test-secret'}})
        result=migrate_legacy(self.config)
        self.assertTrue(result['changed'])
        self.assertTrue(result['restart_required'])
        self.assertEqual(Path(result['backup_path']).read_bytes(),original)
        updated=self.config.read_text(encoding='utf-8')
        self.assertNotIn('xyquant_factors',updated)
        self.assertNotIn('test-secret',updated)
        self.assertIn('# retain comment',updated)
        doc=tomlkit.parse(updated)
        self.assertEqual(doc['mcp_servers']['other']['command'],'another-service')
        self.assertEqual(doc['model'],'unchanged')
        self.assertTrue(doc['plugins']['another@market']['enabled'])
        self.assertEqual((self.state/'credentials.dpapi').read_bytes(),b'encrypted-fixture')
        self.assertEqual((self.state/'downloads.sqlite').read_bytes(),b'fixture-download-records')
        self.assertFalse(migrate_legacy(self.config)['changed'])
        self.assertEqual(len(list(self.config.parent.glob('*.bak'))),1)

    def test_only_known_legacy_bridge_is_removed(self):
        self.seed({'command':str(self.state/'FactorBridge.exe'),'args':['--stdio']})
        self.assertTrue(migrate_legacy(self.config)['changed'])

    def test_unknown_command_url_or_arguments_never_modified(self):
        entries=[
            {'url':'https://another.example/mcp'},
            {'url':ORIGIN+'/mcp','command':'foreign-program'},
            {'command':str(self.root/'other'/'FactorBridge.exe'),'args':['--stdio']},
            {'command':str(self.state/'FactorBridge.exe'),'args':['--stdio','--other']},
            {'command':'FactorBridge.exe','args':['--stdio']},
        ]
        for entry in entries:
            with self.subTest(entry=entry):
                original=self.seed(entry)
                with self.assertRaises(ClientError) as raised:migrate_legacy(self.config)
                self.assertEqual(raised.exception.code,'config_conflict')
                self.assertEqual(self.config.read_bytes(),original)
        self.assertEqual(list(self.config.parent.glob('*.bak')),[])

    def test_missing_or_invalid_config_is_not_replaced(self):
        self.assertFalse(migrate_legacy(self.config)['changed'])
        self.assertFalse(self.config.exists())
        for data in ('not toml','mcp_servers="invalid"'):
            self.config.write_text(data,encoding='utf-8')
            with self.assertRaises(ClientError) as raised:migrate_legacy(self.config)
            self.assertEqual(raised.exception.code,'config_invalid')
            self.assertEqual(self.config.read_text(encoding='utf-8'),data)

    def test_atomic_replace_failure_preserves_config_and_removes_temporary_file(self):
        original=self.seed({'url':ORIGIN+'/mcp'})
        with patch('configuration.Path.replace',side_effect=PermissionError('fixture locked')):
            with self.assertRaises(PermissionError):migrate_legacy(self.config)
        self.assertEqual(self.config.read_bytes(),original)
        self.assertEqual(list(self.config.parent.glob('*.tmp')),[])
        self.assertEqual(next(self.config.parent.glob('*.bak')).read_bytes(),original)


if __name__=='__main__':unittest.main()
