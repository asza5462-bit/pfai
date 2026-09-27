import unittest
from pfai.code_best_of_n import select_best_solution


class TestBestOfN(unittest.TestCase):
    def test_no_candidates(self):
        r = select_best_solution([], "assert True")
        self.assertIsNone(r.best_index)
        self.assertEqual(r.results, [])

    def test_picks_a_passing_candidate_over_failing_ones(self):
        candidates = [
            "def add(a, b):\n    return a - b\n",   # wrong
            "def add(a, b):\n    return a + b\n",   # correct
            "def add(a, b):\n    return a * b\n",   # wrong
        ]
        r = select_best_solution(candidates, "assert add(2, 3) == 5\n")
        self.assertEqual(r.best_index, 1)
        self.assertEqual(r.passing_indices, [1])
        self.assertEqual(len(r.results), 3)

    def test_shortest_passing_candidate_wins_on_tie(self):
        short = "def add(a, b):\n    return a + b\n"
        longer = "def add(a, b):\n    result = a + b\n    return result\n"
        r = select_best_solution([longer, short], "assert add(2, 3) == 5\n")
        self.assertEqual(r.best_code, short)

    def test_no_passing_candidate_returns_none(self):
        candidates = ["def add(a, b):\n    return a - b\n", "def add(a, b):\n    return a * b\n"]
        r = select_best_solution(candidates, "assert add(2, 3) == 5\n")
        self.assertIsNone(r.best_index)
        self.assertIsNone(r.best_code)
        self.assertEqual(r.passing_indices, [])
        self.assertEqual(len(r.results), 2)


if __name__ == '__main__':
    unittest.main()
