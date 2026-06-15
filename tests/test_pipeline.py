import unittest

from branch_and_price.run_bnp import branch_and_price
from compact_model.branch_cut_mci import solve_branch_cut_mci
from compact_model.lp_mci import solution_service_metrics
from data.generate_data import generate_instance


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instance = generate_instance("test", 8, 2, seed=77)

    def test_branch_cut_mci_matches_paper_solution(self):
        paper = branch_and_price(self.instance, time_limit=10)
        branch_cut = solve_branch_cut_mci(self.instance, time_limit=10)
        self.assertEqual(paper["status"], "Optimal")
        self.assertEqual(branch_cut["status"], "Optimal")
        self.assertAlmostEqual(branch_cut["objective"], paper["objective"], places=6)
        self.assertGreaterEqual(branch_cut["mci_candidates"], branch_cut["mci_cuts_added"])

    def test_service_split_matches_total_demand(self):
        paper = branch_and_price(self.instance, time_limit=10)
        metrics = solution_service_metrics(self.instance, paper)
        self.assertAlmostEqual(
            metrics["facility_demand"] + metrics["small_gv_demand"],
            metrics["total_demand"],
            places=6,
        )
        self.assertLessEqual(metrics["small_gv_routes"], metrics["max_small_gvs"])


if __name__ == "__main__":
    unittest.main()
