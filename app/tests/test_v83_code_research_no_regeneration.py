import tempfile
import unittest

from pfai.code_research import CodeResearchLoop, CodeTask, RestrictedPythonRunner


class TestCodeResearchNoRegeneration(unittest.TestCase):
    """Regression test for a real correctness bug: solve() used to call the
    generator a second time, after verification, just to "get the code back"
    for curation. Since `generator` is typically backed by a non-deterministic
    model, that second call could return code that was never executed or
    tested at all -- yet it was curated under metadata 'runtime_verified':
    True. This defeats the entire purpose of ground-truth verification.

    This test uses a generator that returns a *different*, broken snippet on
    every call after the first, so the bug (if reintroduced) is caught
    immediately: the curated response must be exactly the code that actually
    passed, and the generator must be called exactly `max_attempts` times,
    never more.
    """

    def test_curated_code_is_exactly_the_verified_code(self):
        calls = []

        def gen(task, feedback):
            calls.append(1)
            if len(calls) == 1:
                return 'def add(a,b):\n    return a+b\n\nassert add(2,3)==5\n'
            # Any call beyond the first would be the "regenerate for curation"
            # call the old code made. Returning broken code here means the
            # test fails loudly if that call ever happens again.
            return 'def add(a,b):\n    raise RuntimeError("never called")\n'

        with tempfile.TemporaryDirectory() as d:
            loop = CodeResearchLoop(d, runner=RestrictedPythonRunner(timeout_seconds=2))
            task = CodeTask('add', 'Implement add(a,b)', 'assert add(2,3)==5')
            result = loop.solve(task, gen, max_attempts=3)

        self.assertTrue(result['accepted'])
        self.assertEqual(result['learning_items'], 1)
        self.assertEqual(len(calls), 1, 'generator must not be called again after verification')
        self.assertEqual(result['best']['code'],
                          'def add(a,b):\n    return a+b\n\nassert add(2,3)==5\n')


if __name__ == '__main__':
    unittest.main()
