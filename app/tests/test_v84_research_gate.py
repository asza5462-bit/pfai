import json
import tempfile
import unittest

from pfai.policy import Policy
from pfai.research_gate import ResearchGate


class _StubWeb:
    """Stands in for WebTool so these tests never touch the real network."""
    def __init__(self, pages=None, raise_for=None):
        self.pages = pages or {}
        self.raise_for = raise_for or set()
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        if url in self.raise_for:
            raise TimeoutError(f"simulated network failure for {url}")
        return self.pages.get(url, "")


def _gate(tmpdir, *, network=False, allowed_domains=None, web=None, **kw):
    policy = Policy({"allow_network": network, "allowed_domains": allowed_domains or []})
    return ResearchGate(policy, web=web or _StubWeb(), ledger_path=f"{tmpdir}/ledger.jsonl", **kw)


class TestResearchGate(unittest.TestCase):
    def test_denied_by_default_when_network_is_off(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={"https://docs.python.org/x": "hello"})
            gate = _gate(d, network=False, web=stub)
            sources = gate.gather(["https://docs.python.org/x"])
            self.assertEqual(len(sources), 1)
            self.assertFalse(sources[0].allowed)
            self.assertFalse(sources[0].fetched)
            self.assertEqual(stub.calls, [], "must never call WebTool.fetch when policy denies")

    def test_denied_when_domain_not_in_allowlist(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={"https://evil.example/x": "hello"})
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub)
            sources = gate.gather(["https://evil.example/x"])
            self.assertFalse(sources[0].allowed)
            self.assertEqual(stub.calls, [])

    def test_fetches_when_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={"https://docs.python.org/x": "  useful   docs  "})
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub)
            sources = gate.gather(["https://docs.python.org/x"], task_id="t1")
            self.assertTrue(sources[0].allowed)
            self.assertTrue(sources[0].fetched)
            self.assertEqual(sources[0].excerpt, "useful docs")
            self.assertTrue(sources[0].content_hash)

    def test_never_raises_on_fetch_error(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(raise_for={"https://docs.python.org/x"})
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub)
            sources = gate.gather(["https://docs.python.org/x"])
            self.assertTrue(sources[0].allowed)
            self.assertFalse(sources[0].fetched)
            self.assertIn("TimeoutError", sources[0].error)

    def test_respects_max_urls(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={f"https://docs.python.org/{i}": "x" for i in range(10)})
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub, max_urls=2)
            urls = [f"https://docs.python.org/{i}" for i in range(10)]
            sources = gate.gather(urls)
            self.assertEqual(len(sources), 2)
            self.assertEqual(len(stub.calls), 2)

    def test_ledger_chain_is_valid_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={"https://docs.python.org/x": "content"})
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub)
            gate.gather(["https://docs.python.org/x", "https://blocked.example/y"])
            self.assertTrue(gate.verify_chain())

            # Tamper with the ledger file directly and confirm it's detected.
            lines = gate.ledger.read_text(encoding="utf-8").splitlines()
            row = json.loads(lines[0])
            row["url"] = "https://tampered.example/"
            lines[0] = json.dumps(row, sort_keys=True)
            gate.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertFalse(gate.verify_chain())

    def test_format_context_labels_sources_as_untrusted(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={"https://docs.python.org/x": "some reference text"})
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub)
            sources = gate.gather(["https://docs.python.org/x"])
            ctx = gate.format_context(sources)
            self.assertIn("untrusted", ctx)
            self.assertIn("not instructions", ctx)
            self.assertIn("some reference text", ctx)

    def test_format_context_respects_total_budget(self):
        with tempfile.TemporaryDirectory() as d:
            stub = _StubWeb(pages={
                "https://docs.python.org/a": "x" * 100,
                "https://docs.python.org/b": "y" * 100,
            })
            gate = _gate(d, network=True, allowed_domains=["docs.python.org"], web=stub)
            sources = gate.gather(["https://docs.python.org/a", "https://docs.python.org/b"])
            ctx = gate.format_context(sources, max_total_chars=50)
            # The whole budget is spent on the first source's excerpt, so the
            # second source's content must not appear in the context at all.
            self.assertNotIn("y" * 100, ctx)
            self.assertNotIn("docs.python.org/b", ctx)
            self.assertLessEqual(ctx.count("x" * 10), 5)  # at most ~50 'x' chars total


if __name__ == "__main__":
    unittest.main()
