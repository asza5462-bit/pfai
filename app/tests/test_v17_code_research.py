import tempfile, unittest
from pathlib import Path
from pfai.code_research import CodeResearchLoop, CodeTask, RestrictedPythonRunner

class TestV17CodeResearch(unittest.TestCase):
    def test_verified_solution_becomes_learning_item(self):
        with tempfile.TemporaryDirectory() as d:
            loop=CodeResearchLoop(d, runner=RestrictedPythonRunner(timeout_seconds=2))
            task=CodeTask('add','Implement add(a,b)','assert add(2,3)==5')
            def gen(t, feedback):
                return 'def add(a,b):\n    return a+b\n\nassert add(2,3)==5\n'
            r=loop.solve(task,gen,max_attempts=2)
            self.assertTrue(r['accepted']); self.assertEqual(r['learning_items'],1)

    def test_failed_runtime_is_not_learned(self):
        with tempfile.TemporaryDirectory() as d:
            loop=CodeResearchLoop(d, runner=RestrictedPythonRunner(timeout_seconds=1))
            task=CodeTask('bad','Implement add(a,b)','assert add(2,3)==5')
            def gen(t, feedback): return 'def add(a,b):\n    return a-b\n'
            r=loop.solve(task,gen,max_attempts=2)
            self.assertFalse(r['accepted']); self.assertEqual(r['learning_items'],0)

    def test_static_gate_blocks_unsafe_import(self):
        with tempfile.TemporaryDirectory() as d:
            loop=CodeResearchLoop(d)
            task=CodeTask('unsafe','Do task','assert True')
            def gen(t, feedback): return 'import os\ndef x():\n    return 1\n'
            r=loop.solve(task,gen,max_attempts=1)
            self.assertFalse(r['accepted'])

if __name__=='__main__': unittest.main()
