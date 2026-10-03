import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import diagnostics


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_only_allowlisted_fields_and_values_are_recorded(self):
        diagnostics.record(self.root,'list_factors','complete',12.75,'ok','a'*32)
        for tool,stage,code,trace in [('private-username','complete','ok','a'*32),
                                      ('list_factors','C:/private/project','ok','a'*32),
                                      ('list_factors','complete','Bearer private-token','a'*32),
                                      ('list_factors','complete','ok','Authorization: private')]:
            diagnostics.record(self.root,tool,stage,1,code,trace)
        data=(self.root/'diagnostics/requests.jsonl').read_text()
        rows=[json.loads(line) for line in data.splitlines()]
        self.assertEqual(len(rows),1)
        self.assertEqual(set(rows[0]),{'tool','stage','elapsed_ms','code','request_id'})
        self.assertNotIn('private',data)
        self.assertNotIn('Authorization',data)

    def test_bounded_rotation_keeps_only_current_and_previous(self):
        with patch('diagnostics.MAX_BYTES',512):
            for _ in range(30):diagnostics.record(self.root,'get_export','request',1,'busy','a'*32)
        files=list((self.root/'diagnostics').iterdir())
        self.assertEqual({p.name for p in files},{'requests.jsonl','requests.previous.jsonl'})
        self.assertTrue(all(p.stat().st_size<=512 for p in files))
        for path in files:
            for line in path.read_text().splitlines():json.loads(line)

    def test_bad_trace_is_regenerated_without_carrying_arbitrary_input(self):
        for value in (None,'Bearer private','a'*31,'A'*32,123):
            self.assertRegex(diagnostics.trace_id(value),r'^[a-f0-9]{32}$')
        self.assertEqual(diagnostics.trace_id('b'*32),'b'*32)

    def test_disk_failure_or_lock_contention_cannot_break_request(self):
        with patch.object(Path,'open',side_effect=OSError('private path must not escape')):
            diagnostics.record(self.root,'get_export','request',1,'ok','a'*32)
        with patch('diagnostics.mutex',side_effect=diagnostics.ClientError('busy','busy')):
            diagnostics.record(self.root,'get_export','request',1,'ok','a'*32)

    def test_unsafe_paths_or_nonfinite_duration_do_not_write(self):
        diagnostics.record(None,'get_export','request',1,'ok','a'*32)
        diagnostics.record('relative','get_export','request',1,'ok','a'*32)
        diagnostics.record(self.root,'get_export','request',float('nan'),'ok','a'*32)
        self.assertFalse((self.root/'diagnostics').exists())


if __name__=='__main__':unittest.main()
