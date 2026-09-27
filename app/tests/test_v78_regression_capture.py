import tempfile
import unittest

from pfai.regression_capture import RegressionCapture


BROKEN = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
TEST = "assert add(2, 3) == 5\n"


class TestRegressionCapture(unittest.TestCase):
    def test_capture_accepts_a_genuine_regression(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RegressionCapture(root=d)
            result = rc.capture('add() had subtraction instead of addition', BROKEN, FIXED, TEST)
            self.assertTrue(result['queued'])
            self.assertEqual(len(rc.pending()), 1)

    def test_capture_rejects_when_broken_code_does_not_actually_fail(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RegressionCapture(root=d)
            # "broken" code that actually already passes -- not a real regression
            result = rc.capture('fake regression', FIXED, FIXED, TEST)
            self.assertFalse(result['queued'])
            self.assertEqual(rc.pending(), [])

    def test_capture_rejects_when_fix_does_not_actually_pass(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RegressionCapture(root=d)
            still_broken = "def add(a, b):\n    return a * b\n"
            result = rc.capture('bad fix', BROKEN, still_broken, TEST)
            self.assertFalse(result['queued'])
            self.assertEqual(rc.pending(), [])

    def test_materialize_writes_a_real_test_file_and_it_actually_passes(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RegressionCapture(root=d)
            queued = rc.capture('add() sign bug', BROKEN, FIXED, TEST)
            case_id = queued['case_id']

            with tempfile.TemporaryDirectory() as tests_dir:
                out = rc.materialize(case_id, tests_dir=tests_dir)
                self.assertTrue(out['materialized'])

                # The generated file must itself be valid, runnable, passing unittest code.
                namespace = {}
                with open(out['path'], encoding='utf-8') as fh:
                    src = fh.read()
                compiled = compile(src, out['path'], 'exec')
                exec(compiled, namespace)
                test_case_cls = namespace[f"TestRegression_{case_id}"]
                suite = unittest.TestLoader().loadTestsFromTestCase(test_case_cls)
                result = unittest.TextTestRunner(verbosity=0).run(suite)
                self.assertTrue(result.wasSuccessful())

            # No longer pending once materialized.
            self.assertEqual(rc.pending(), [])

    def test_materialize_unknown_case_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RegressionCapture(root=d)
            result = rc.materialize('does-not-exist')
            self.assertFalse(result['materialized'])

    def test_reject_removes_case_from_pending(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RegressionCapture(root=d)
            queued = rc.capture('add() sign bug', BROKEN, FIXED, TEST)
            rc.reject(queued['case_id'])
            self.assertEqual(rc.pending(), [])


if __name__ == '__main__':
    unittest.main()
