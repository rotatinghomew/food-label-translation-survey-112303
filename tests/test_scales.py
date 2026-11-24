"""尺度核对：盲测配对、方向、阈值与顺序混杂。"""
import math
import unittest

from workbench.scales import (
    MIN_PAIRS,
    anchor_equivalence,
    build_pairs,
    non_anchor_coverage,
    scale_check,
    wilson_interval,
)

from workbench_case import WorkbenchCase


class ScaleTests(WorkbenchCase):
    def test_v1_v2_anchors_fail_and_are_order_confounded(self):
        data = self.load()
        for anchor in ("a", "b"):
            rep = anchor_equivalence(data, "V1", "V2", anchor)
            self.assertEqual(rep.status, "失败")
            self.assertTrue(rep.order_confounded)
            self.assertEqual(rep.n_pairs, 9)
            self.assertEqual(rep.n_disagree, 4)
            self.assertIn("熟练", rep.applies_to)

    def test_v1_v2_directional_discordance_for_total_sugar(self):
        data = self.load()
        rep = anchor_equivalence(data, "V1", "V2", "a")
        # 总糖锚题以 V1 正确 -> V2 误解为主，印证 V2 译法问题
        self.assertGreater(rep.n_correct_to_wrong, rep.n_wrong_to_correct)
        self.assertEqual(rep.n_correct_to_wrong, 3)

    def test_v3_v1_total_sugar_supported_via_perfect_agreement(self):
        data = self.load()
        rep = anchor_equivalence(data, "V3", "V1", "a")
        self.assertEqual(rep.status, "成立")
        self.assertEqual(rep.n_pairs, 5)
        self.assertEqual(rep.n_agree, 5)
        self.assertFalse(rep.order_confounded)  # V1/V3 题序一致，顺序效应可分

    def test_v3_v1_added_sugar_inconclusive_for_thin_sample(self):
        data = self.load()
        rep = anchor_equivalence(data, "V3", "V1", "b")
        self.assertEqual(rep.status, "证据不足")
        self.assertLess(rep.n_pairs, MIN_PAIRS)

    def test_reverse_orientation_pairs_are_collected(self):
        # rounds 里 V3->V1 的设计方向，在数据中体现为 V3 主版者做 V1 盲测；
        # 无向版本对 V3<->V1 必须把这些反向观察收进来
        data = self.load()
        pairs, missing = build_pairs(data, "V3", "V1", "a")
        persons = {p.person for p in pairs}
        reverse_persons = {
            r.person
            for r in data.active_responses()
            if r.bridge == "盲复测" and r.version == "V1"
        }
        self.assertTrue(reverse_persons)
        self.assertEqual(persons, reverse_persons)
        self.assertGreaterEqual(missing, 0)

    def test_scale_check_dedups_undirected_pairs(self):
        data = self.load()
        reports = scale_check(data)
        pairs = {(r.version_a, r.version_b) for r in reports}
        # V1<->V2 只能出现一次（rounds 里有两个方向的设计）
        self.assertEqual(len(pairs), 2)
        self.assertIn(("V1", "V2"), pairs)
        self.assertIn(("V3", "V1"), pairs)
        v1v2 = next(r for r in reports if (r.version_a, r.version_b) == ("V1", "V2"))
        self.assertFalse(v1v2.separable_order)
        self.assertTrue(v1v2.person_fluent_only)
        self.assertEqual(len(v1v2.observed_orientations), 2)

    def test_shown_answer_interviews_never_enter_pairs(self):
        data = self.load()
        pairs, _ = build_pairs(data, "V3", "V1", "a")
        # 只做过"访谈（先看答案）"、没做过盲测的人不能产生等值配对
        blind_persons = {r.person for r in data.responses if r.bridge == "盲复测"}
        interview_only_persons = {
            r.person for r in data.responses if r.bridge == "访谈"
        } - blind_persons
        self.assertFalse(
            any(p.person in interview_only_persons for p in pairs)
        )
        # 数据里确有访谈行，证明它们被单独隔离在等值计算之外
        self.assertTrue(interview_only_persons)

    def test_non_anchors_cannot_support_cross_language(self):
        data = self.load()
        coverage = non_anchor_coverage(data)
        items = {c.item: c for c in coverage}
        self.assertEqual(set(items), {"q13", "q23"})
        for cov in coverage:
            self.assertFalse(cov.cross_language_supported)

    def test_wilson_interval_math(self):
        low, high = wilson_interval(5, 9)
        self.assertAlmostEqual(low, 0.2668, places=3)
        self.assertAlmostEqual(high, 0.8114, places=3)
        self.assertTrue(all(math.isnan(x) for x in wilson_interval(0, 0)))


if __name__ == "__main__":
    unittest.main()
