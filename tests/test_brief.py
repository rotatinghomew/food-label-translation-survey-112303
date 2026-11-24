"""轮次简报：框规模对账、两类误解证据分列、撤回影响与适用范围。"""
import unittest

from workbench.brief import bridge_integrity_after_withdrawal

from workbench_case import WorkbenchCase


class BriefTests(WorkbenchCase):
    def setUp(self):
        super().setUp()
        self.result = self.pipeline()
        self.brief = self.result["round_brief"]

    def test_frame_totals_reconcile_to_roster(self):
        strata = self.brief.strata
        self.assertEqual(sum(s.eligible for s in strata), 160)
        self.assertEqual(sum(s.contacted for s in strata), 140)
        self.assertEqual(sum(s.never_contacted for s in strata), 20)
        self.assertEqual(sum(s.invited_nonresponse for s in strata), 13)
        self.assertEqual(sum(s.valid_respondents for s in strata), 127)
        # 恒等：接触 = 有效 + 已邀请未答；合资格 = 接触 + 未接触
        for s in strata:
            self.assertEqual(s.contacted + s.never_contacted, s.eligible)
            self.assertEqual(s.valid_respondents + s.invited_nonresponse, s.contacted)

    def test_two_misconceptions_reported_separately(self):
        for s in self.brief.strata:
            self.assertEqual(set(s.misconception_evidence), {"总糖", "添加"})
            self.assertEqual(set(s.observed_items), {"总糖", "添加"})
            for concept in ("总糖", "添加"):
                self.assertGreaterEqual(s.observed_items[concept], 0)
                self.assertLessEqual(
                    s.misconception_evidence[concept], s.observed_items[concept]
                )

    def test_gap_split_keeps_never_contacted_separate(self):
        # 电话层存在未接触者，现场层全部接触；两类缺口在简报里分列
        phone = [s for s in self.brief.strata if s.channel == "电话"]
        field = [s for s in self.brief.strata if s.channel == "现场"]
        self.assertTrue(all(s.never_contacted >= 6 for s in phone))
        self.assertTrue(all(s.never_contacted == 0 for s in field))
        self.assertTrue(all(s.invited_nonresponse >= 1 for s in self.brief.strata))

    def test_withdrawal_weakens_bridge_but_keeps_standalone_estimates(self):
        lines = bridge_integrity_after_withdrawal(self.result["data"])
        joined = "\n".join(lines)
        self.assertIn("r012b1", joined)
        self.assertIn("单独估计", joined)
        self.assertIn("V1", joined)
        self.assertIn("V2", joined)
        self.assertIn("V3", joined)

    def test_applicability_states_fluent_scope_and_no_bridge_language(self):
        text = "\n".join(self.brief.applicability)
        # 桥接只覆盖熟练读者，必须明说适用范围
        self.assertIn("熟练", text)
        # 河湾语没有桥接样本，单独估计有效但跨语言差距无支撑
        self.assertIn("河湾语", text)
        self.assertIn("不能由其他语言的题强行补齐", text)

    def test_deactivation_listed_with_effective_day(self):
        self.assertEqual(self.brief.deactivations, {"V2": "2026-10-13"})
        self.assertEqual(self.brief.withdrawals, ["r012b1"])


if __name__ == "__main__":
    unittest.main()
