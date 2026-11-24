"""分层估计：口径、边界、撤回隔离与跨语言差距门禁。"""
import math
import unittest

from workbench.estimates import (
    cross_language_gaps,
    rollup_language,
    stratified_estimates,
)
from workbench.scales import scale_check

from workbench_case import WorkbenchCase


def _supported(reports):
    return {
        (rep.version_a, rep.version_b, rep.anchor)
        for report in reports
        for rep in report.anchor_reports
        if rep.status == "成立"
    }


class EstimateTests(WorkbenchCase):
    def setUp(self):
        super().setUp()
        result = self.pipeline()
        self.data = result["data"]
        self.reports = result["scale_reports"]
        self.estimates = result["estimates"]
        self.rollups = result["rollups"]
        self.gaps = result["gaps"]

    def _est(self, preferred, channel, concept):
        return next(
            e
            for e in self.estimates
            if e.preferred == preferred
            and e.channel == channel
            and e.concept == concept
        )

    def test_frame_and_gap_split_matches_roster(self):
        # 河湾语/现场：27 合资格、全部接触、3 名已邀请未答
        est = self._est("河湾语", "现场", "总糖")
        self.assertEqual(est.n_frame, 27)
        self.assertEqual(est.n_contacted, 27)
        self.assertEqual(est.n_never_contacted, 0)
        self.assertEqual(est.n_invited_nonresponse, 3)
        # 河湾语/电话：26 合资格、7 名根本未接触
        est2 = self._est("河湾语", "电话", "总糖")
        self.assertEqual(est2.n_frame, 26)
        self.assertEqual(est2.n_never_contacted, 7)
        self.assertEqual(est2.n_contacted, 19)

    def test_point_estimate_matches_manual_rate(self):
        # 河湾语/现场 添加：12/23 = 0.5217（层内权重恒定，加权=未加权）
        est = self._est("河湾语", "现场", "添加")
        self.assertEqual(est.n_misconception, 12)
        self.assertEqual(est.n_observed, 23)
        self.assertAlmostEqual(est.point, 12 / 23, places=6)

    def test_bounds_bracket_point_and_only_cover_contacted_frame(self):
        for est in self.estimates:
            if not math.isnan(est.point):
                self.assertLessEqual(est.low_bound, est.point + 1e-12)
                self.assertLessEqual(est.point, est.high_bound + 1e-12)
        # 有未接触者的层：备注必须提示另一邀请框
        est = self._est("普通话", "电话", "总糖")
        self.assertTrue(any("未接触" in n for n in est.notes))

    def test_withdrawal_does_not_change_standalone_rates(self):
        # 撤回的是盲测行；原版口径下各语言单独估计与"忽略撤回"的原版统计一致
        baseline = {}
        for est in self.estimates:
            baseline[(est.preferred, est.channel, est.concept)] = est.point
        fresh = self.load()
        fresh_reports = scale_check(fresh)
        fresh_est = stratified_estimates(fresh, _supported(fresh_reports))
        for est in fresh_est:
            key = (est.preferred, est.channel, est.concept)
            if not math.isnan(baseline[key]):
                self.assertAlmostEqual(est.point, baseline[key], places=9)

    def test_only_supported_concepts_are_marked_comparable(self):
        # 总糖锚题 a 在 V3<->V1 成立：普通话/山城语 标可比；河湾语仅本译版
        self.assertEqual(self._est("普通话", "电话", "总糖").scale_status, "可比")
        self.assertEqual(self._est("山城语", "现场", "总糖").scale_status, "可比")
        self.assertEqual(self._est("河湾语", "现场", "总糖").scale_status, "仅本译版")
        # 添加概念没有任何成立桥接
        for est in self.estimates:
            if est.concept == "添加":
                self.assertIn(est.scale_status, ("无桥接支撑", "仅本译版"))

    def test_gaps_blocked_without_bridge_but_reported(self):
        blocked = [g for g in self.gaps if g["status"] == "尺度未验证"]
        allowed = [g for g in self.gaps if g["status"] == "可比较"]
        # 唯一可比较差距：总糖 山城语-普通话
        self.assertEqual(len(allowed), 1)
        gap = allowed[0]
        self.assertEqual((gap["concept"], gap["language_a"], gap["language_b"]),
                         ("总糖", "山城语", "普通话"))
        self.assertFalse(math.isnan(gap["gap"]))
        # 河湾语涉及的所有差距都必须被拦
        self.assertTrue(
            all(
                g["status"] == "尺度未验证"
                for g in blocked
                if "河湾语" in (g["language_a"], g["language_b"])
            )
        )
        for g in blocked:
            self.assertTrue(math.isnan(g["gap"]))

    def test_rollup_is_weighted_and_keeps_scale_status(self):
        roll = next(
            r for r in self.rollups
            if r.preferred == "河湾语" and r.concept == "总糖"
        )
        # 河湾语总糖：现场 15/47（w=1/0.6），电话 16/32（w=1/0.32）
        w_mis = 15 / 0.6 + 16 / 0.32
        w_obs = 47 / 0.6 + 32 / 0.32
        self.assertAlmostEqual(roll.point, w_mis / w_obs, places=6)
        self.assertEqual(roll.scale_status, "仅本译版")

    def test_analysis_only_respondents_still_estimated_but_flagged(self):
        # 山城语有 17 名只准分析；估计照算，但补访侧不可触达（在 scheduler 测试验证）
        est = self._est("山城语", "现场", "总糖")
        self.assertGreater(est.n_analysis_only, 0)
        self.assertGreater(est.n_observed, 0)

    def test_never_contacted_excluded_from_bounds_denominator(self):
        # 普通话/电话：7 名未接触者在另一框，边界分母只含已接触框
        est = self._est("普通话", "电话", "总糖")
        contacted_persons = [
            p for p, inv in self.data.invitations.items()
            if inv.preferred == "普通话" and inv.channel == "电话" and inv.contacted
        ]
        # 下界 = 加权误解 / （已接触框全部应答题次的权重）
        expected_denom = sum(
            1.0 / self.data.invitations[p].selection_p
            for p in contacted_persons
        ) * len(est.items)
        self.assertAlmostEqual(
            est.low_bound, est.weighted_misconception / expected_denom, places=9
        )
        # 上界把已接触框未观察全算误解，仍不碰未接触者
        self.assertAlmostEqual(
            est.high_bound,
            (est.weighted_misconception + est.weighted_unobserved) / expected_denom,
            places=9,
        )

    def test_missing_item_codes_count_as_unobserved_not_misconception(self):
        # 存在逐题缺失的层：缺失不计入误解证据，但进入边界宽度
        any_missing = [e for e in self.estimates if e.n_missing_items > 0]
        self.assertTrue(any_missing)
        for est in any_missing:
            self.assertEqual(
                est.n_observed, est.n_misconception + est.n_correct
            )
            self.assertGreater(est.weighted_unobserved, 0.0)
            self.assertLess(est.low_bound, est.high_bound)

    def test_estimates_only_use_original_responses(self):
        # 工作台口径：盲测与先看答案的访谈都不进入总体估计
        original_rows = [
            r for r in self.data.active_responses() if r.bridge == "原版"
        ]
        # 各层观察题次之和必须等于原版有效（非缺失、非撤回）行数
        observed_total = sum(e.n_observed for e in self.estimates)
        original_observed = sum(1 for r in original_rows if r.code != "")
        self.assertEqual(observed_total, original_observed)
        # 盲测/访谈行数确实存在，证明它们是被显式排除而不是数据里没有
        self.assertTrue(
            any(r.bridge != "原版" for r in self.data.active_responses())
        )


if __name__ == "__main__":
    unittest.main()
