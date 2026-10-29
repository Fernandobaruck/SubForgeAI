import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ollama_script as O


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        mocked=patch("studio_ui.gpu_policy.ensure_ollama_gpu");mocked.start();self.addCleanup(mocked.stop)

    def response(self, lines):
        response = Mock(status_code=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_lines.return_value = [json.dumps(line).encode() for line in lines]
        return response

    def test_complete_stream(self):
        response = self.response([{'message': {'content': 'Olá'}}, {'done': True}])
        with patch.object(O.requests, 'post', return_value=response) as post:
            self.assertEqual(O._ollama_call('test', []), 'Olá')
            self.assertTrue(post.call_args.kwargs['stream'])
            self.assertTrue(post.call_args.kwargs['json']['stream'])
        response.__exit__.assert_called_once()

    def test_partial_stream_is_rejected(self):
        with patch.object(O.requests, 'post', return_value=self.response([{'response': 'parcial'}])):
            with self.assertRaises(O.OllamaTransientError):
                O._ollama_call('test', [])

    def test_timeout_splits_batch(self):
        calls = []
        def request(model, items):
            calls.append(list(items))
            if len(items) > 1:
                raise O.OllamaTransientError('timeout')
            return ['traduzido ' + items[0]]
        self.assertEqual(O._call_with_retries_generic('test', ['a', 'b'], request),
                         ['traduzido a', 'traduzido b'])
        self.assertEqual(calls, [['a', 'b'], ['a'], ['b']])

    def test_unavailable_server_has_bounded_retries(self):
        request = Mock(side_effect=O.OllamaTransientError('offline'))
        with patch.object(O.time, 'sleep'):
            with self.assertRaises(O.OllamaTransientError):
                O._call_with_retries_generic('test', ['a'], request)
        self.assertEqual(request.call_count, O.MAX_RETRIES)


if __name__ == '__main__':
    unittest.main()
