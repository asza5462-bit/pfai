import io, json, os, unittest
from unittest.mock import patch
from pfai.model_anthropic import AnthropicProvider


class _FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


class TestAnthropicProvider(unittest.TestCase):
    def _clean_env(self, *names):
        saved = {n: os.environ.pop(n, None) for n in names}
        self.addCleanup(lambda: [os.environ.pop(n, None) if v is None else os.environ.__setitem__(n, v)
                                  for n, v in saved.items()])

    def test_generate_fails_closed_without_api_key(self):
        self._clean_env('ANTHROPIC_API_KEY')
        provider = AnthropicProvider()
        with self.assertRaises(RuntimeError):
            provider.generate('hello')

    def test_generate_rejects_empty_prompt(self):
        self._clean_env('ANTHROPIC_API_KEY')
        os.environ['ANTHROPIC_API_KEY'] = 'test-key'
        provider = AnthropicProvider()
        with self.assertRaises(ValueError):
            provider.generate('   ')

    def test_generate_sends_expected_request_and_parses_text(self):
        self._clean_env('ANTHROPIC_API_KEY')
        os.environ['ANTHROPIC_API_KEY'] = 'test-key'
        provider = AnthropicProvider(model='claude-opus-5', max_tokens=128)

        fake_body = json.dumps({'content': [{'type': 'text', 'text': 'answer text'}]}).encode()

        captured = {}
        def fake_urlopen(req, timeout=None):
            captured['url'] = req.full_url
            captured['headers'] = {k.lower(): v for k, v in req.headers.items()}
            captured['payload'] = json.loads(req.data.decode())
            return _FakeResponse(fake_body)

        with patch('pfai.model_anthropic.urllib.request.urlopen', side_effect=fake_urlopen):
            result = provider.generate('what is 2+2?', temperature=0.1)

        self.assertEqual(result, 'answer text')
        self.assertEqual(captured['url'], 'https://api.anthropic.com/v1/messages')
        self.assertEqual(captured['headers'].get('x-api-key'), 'test-key')
        self.assertEqual(captured['headers'].get('anthropic-version'), '2023-06-01')
        self.assertEqual(captured['payload']['model'], 'claude-opus-5')
        self.assertEqual(captured['payload']['max_tokens'], 128)
        self.assertEqual(captured['payload']['messages'], [{'role': 'user', 'content': 'what is 2+2?'}])

    def test_current_default_model_omits_deprecated_temperature(self):
        self._clean_env('ANTHROPIC_API_KEY')
        os.environ['ANTHROPIC_API_KEY']='test-key'
        provider=AnthropicProvider(max_tokens=64)
        body=json.dumps({'content':[{'type':'text','text':'ok'}]}).encode()
        captured={}
        def fake_urlopen(req, timeout=None):
            captured['payload']=json.loads(req.data.decode())
            return _FakeResponse(body)
        with patch('pfai.model_anthropic.urllib.request.urlopen', side_effect=fake_urlopen):
            self.assertEqual(provider.generate('hello', temperature=0.1), 'ok')
        self.assertEqual(captured['payload']['model'],'claude-opus-5')
        self.assertNotIn('temperature',captured['payload'])

    def test_generate_raises_on_empty_text_content(self):
        self._clean_env('ANTHROPIC_API_KEY')
        os.environ['ANTHROPIC_API_KEY'] = 'test-key'
        provider = AnthropicProvider()
        fake_body = json.dumps({'content': []}).encode()

        with patch('pfai.model_anthropic.urllib.request.urlopen',
                   return_value=_FakeResponse(fake_body)):
            with self.assertRaises(RuntimeError):
                provider.generate('hello')

    def test_api_key_is_never_read_from_config(self):
        # The constructor accepts no api_key argument at all — only an env var name.
        self.assertNotIn('api_key', AnthropicProvider.__init__.__code__.co_varnames)


if __name__ == '__main__':
    unittest.main()
