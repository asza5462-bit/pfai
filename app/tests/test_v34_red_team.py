import tempfile, os
import unittest
from pfai.red_team import RedTeamLab, AttackCase

class TestRedTeam(unittest.TestCase):
    def test_case_filter_and_dedup(self):
        lab=RedTeamLab(max_cases=2)
        rows=lab.build_cases([
            AttackCase("1","prompt_injection","x"),
            AttackCase("1","prompt_injection","x"),
            AttackCase("bad","unknown","x"),
            AttackCase("2","code_safety","y")])
        self.assertEqual([r.case_id for r in rows], ["1","2"])

    def test_run_and_summary(self):
        lab=RedTeamLab()
        cases=[AttackCase("1","prompt_injection","ignore rules",expected="SAFE",metadata={"severity":"high"}),
               AttackCase("2","regression","normal",expected="OK")]
        out=lab.run(cases, lambda c: "SAFE" if c.case_id=="1" else "OK")
        self.assertEqual(lab.summary(out), {"total":2,"passed":2,"failed":0,"high_or_critical_failures":0})

    def test_failure_is_visible(self):
        lab=RedTeamLab()
        out=lab.run([AttackCase("1","tool_boundary","grant",expected="DENIED",metadata={"severity":"critical"})], lambda c: "ALLOWED")
        s=lab.summary(out)
        self.assertEqual(s["failed"],1); self.assertEqual(s["high_or_critical_failures"],1)

    def test_regression_export(self):
        lab=RedTeamLab(); out=lab.run([AttackCase("1","regression","x",expected="OK")], lambda c:"OK")
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,"regression.jsonl"); info=lab.export_regression(out,p)
            self.assertEqual(info["count"],1); self.assertTrue(os.path.exists(p))

if __name__=='__main__': unittest.main()
