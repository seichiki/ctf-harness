import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.deepseek_preflight import attempt, load_api_key, KeyFileError


class FakeResponse:
    def __init__(self, body):
        self.body = io.BytesIO(json.dumps(body).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size):
        return self.body.read(size)


class DeepSeekPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.input = self.root / 'input'
        self.input.mkdir()
        (self.input / 'statement.txt').write_text('What is 2 + 3?', encoding='utf-8')
        (self.input / 'binary.bin').write_bytes(b'\x00\xff')
        self.config = {'deepseek_model': 'deepseek-flash'}
        self.key_file = self.root / '.env'
        self.key_patch = patch('harness.deepseek_preflight.DOTENV_FILE', self.key_file)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    def test_private_dotenv_is_used_when_environment_is_empty(self):
        self.key_file.write_text('# local key\nDEEPSEEK_API_KEY="file-secret"\n', encoding='utf-8')
        self.key_file.chmod(0o600)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}):
            self.assertEqual(load_api_key(), 'file-secret')

    def test_environment_overrides_dotenv(self):
        self.key_file.write_text('DEEPSEEK_API_KEY=file-secret\n', encoding='utf-8')
        self.key_file.chmod(0o600)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'env-secret'}):
            self.assertEqual(load_api_key(), 'env-secret')

    def test_dotenv_with_loose_permissions_is_rejected(self):
        self.key_file.write_text('DEEPSEEK_API_KEY=file-secret\n', encoding='utf-8')
        self.key_file.chmod(0o644)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}):
            with self.assertRaises(KeyFileError):
                load_api_key()

    def test_success_sends_text_only_and_saves_candidate(self):
        answer = {'candidate': 'ctf{5}', 'attempts': ['added 2 and 3'],
                  'reason': '5 is the sum', 'limitations': ['not verified']}
        body = {'choices': [{'message': {'content': json.dumps(answer)}}], 'usage': {'total_tokens': 42}}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-secret'}), patch(
                'harness.deepseek_preflight.urllib.request.urlopen', return_value=FakeResponse(body)) as call:
            record = attempt(self.input, self.root, self.config, time.monotonic() + 10)
        sent = json.loads(call.call_args.args[0].data)
        self.assertIn('statement.txt', sent['messages'][1]['content'])
        self.assertNotIn('binary.bin', sent['messages'][1]['content'])
        self.assertEqual(record['candidate'], 'ctf{5}')
        self.assertEqual(record['status'], 'completed')
        saved = (self.root / 'deepseek-handoff.json').read_text(encoding='utf-8')
        self.assertNotIn('test-secret', saved)

    def test_missing_key_records_failure_and_keeps_handoff(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': ''}), patch(
                'harness.deepseek_preflight.urllib.request.urlopen') as call:
            record = attempt(self.input, self.root, self.config, time.monotonic() + 10)
        call.assert_not_called()
        self.assertEqual(record['status'], 'skipped_missing_key')
        self.assertTrue((self.root / 'deepseek-handoff.json').is_file())

    def test_invalid_response_records_failure(self):
        body = {'choices': [{'message': {'content': '{"candidate":"a"}'}}]}
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-secret'}), patch(
                'harness.deepseek_preflight.urllib.request.urlopen', return_value=FakeResponse(body)):
            record = attempt(self.input, self.root, self.config, time.monotonic() + 10)
        self.assertEqual(record['status'], 'failed')
        self.assertIsNone(record['candidate'])


if __name__ == '__main__':
    unittest.main()
