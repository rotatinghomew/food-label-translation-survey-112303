"""补访安排：硬约束、改期锁、停用影响与优先级。"""
import unittest

from workbench.io import BRIDGE_BLIND, BRIDGE_SHOWN, CONSENT_ANALYSIS_ONLY
from workbench.scheduler import (
    assess_appointments,
    rank_followups,
    seat_inventory,
    training_readiness,
)

from workbench_case import WorkbenchCase


class SchedulerTests(WorkbenchCase):
    def setUp(self):
        super().setUp()
        result = self.pipeline()
        self.data = result["data"]
        self.reports = result["scale_reports"]
        self.estimates = result["estimates"]
        self.gaps = result["gaps"]

    def _slot(self, assessments, slot):
        return next(a for a in assessments if a.slot == slot)

    def test_booked_slot_before_rebook_date_stays_locked(self):
        # today=2026-10-14，k3 的 rebook_after=2026-10-15
        assessments = assess_appointments(self.data, "2026-10-14")
        k3 = self._slot(assessments, "k3")
        self.assertTrue(k3.locked)
        self.assertTrue(any("改期" in p for p in k3.problems))
        # 过了改期日就不再锁定
        assessments2 = assess_appointments(self.data, "2026-10-15")
        self.assertFalse(self._slot(assessments2, "k3").locked)

    def test_ineligible_booked_person_flagged(self):
        assessments = assess_appointments(self.data, "2026-10-14")
        for slot in ("k1", "k3"):
            a = self._slot(assessments, slot)
            self.assertTrue(any("桥接资格" in p for p in a.problems))

    def test_deactivated_version_blocks_open_design_and_explains_tradeoff(self):
        assessments = assess_appointments(self.data, "2026-10-14")
        k1 = self._slot(assessments, "k1")
        self.assertTrue(k1.uses_deactivated)
        self.assertIn("V2", k1.comparability_note)
        plan = rank_followups(self.data, "2026-10-14", self.reports, self.estimates)
        # k1 是已预约席位（不是开放席位）：不会进入候选排序，停用影响在评估里交代
        self.assertTrue(all(c.slot != "k1" for c in plan.ranked))
        # 开放席位若指向停用版则进入 skipped；当前数据中 k1 为已预约，
        # 因此这里改为校验库存里河湾语没有可用开放席位
        inventory = seat_inventory(self.data, "2026-10-14")
        self.assertEqual(inventory["河湾语"]["open_seats"], 0)

    def test_mutual_exclusion_blind_vs_shown(self):
        plan = rank_followups(self.data, "2026-10-14", self.reports, self.estimates)
        done_blind = {
            r.person for r in self.data.active_responses() if r.bridge == BRIDGE_BLIND
        }
        done_shown = {
            r.person for r in self.data.active_responses() if r.bridge == BRIDGE_SHOWN
        }
        for c in plan.ranked:
            if c.kind == BRIDGE_BLIND:
                self.assertNotIn(c.person, done_shown)
            if c.kind == BRIDGE_SHOWN:
                self.assertNotIn(c.person, done_blind)
        # 已完成盲测的 p004 若被考虑进访谈席位，必须出现在拦截记录或被排除
        k4_blocked_persons = {b.person for b in plan.blocked if b.slot == "k4"}
        self.assertIn("p004", k4_blocked_persons)

    def test_analysis_only_cannot_be_followup_candidate(self):
        plan = rank_followups(self.data, "2026-10-14", self.reports, self.estimates)
        analysis_only = {
            p for p, inv in self.data.invitations.items()
            if inv.consent == CONSENT_ANALYSIS_ONLY
        }
        self.assertTrue(analysis_only)
        self.assertFalse(any(c.person in analysis_only for c in plan.ranked))

    def test_one_ranked_candidate_per_open_slot_and_pool_count(self):
        plan = rank_followups(self.data, "2026-10-14", self.reports, self.estimates)
        ranked_slots = [c.slot for c in plan.ranked]
        # k4 是同版 V3->V3 访谈，不修复跨语言连接，被跳过；只剩 k2 参与排序
        self.assertEqual(sorted(ranked_slots), ["k2"])
        self.assertEqual(len(ranked_slots), len(set(ranked_slots)))
        self.assertEqual(plan.pool_sizes["k2"], 51)
        self.assertTrue(any(s["slot"] == "k4" for s in plan.skipped_slots))

    def test_inventory_counts(self):
        inventory = seat_inventory(self.data, "2026-10-14")
        # 河湾语唯一席位 k1 指向停用版，开放席位为 0
        self.assertEqual(inventory["河湾语"]["open_seats"], 0)
        self.assertEqual(inventory["河湾语"]["booked_problem"], 1)
        # 山城语：k2、k4 开放，k3 锁定
        self.assertEqual(inventory["山城语"]["open_seats"], 2)
        self.assertEqual(inventory["山城语"]["booked_locked"], 1)

    def test_open_slot_pointing_at_deactivated_version_is_skipped(self):
        # 构造一个指向停用版 V2 的开放席位，必须进入 skipped 且不产生候选
        import csv

        with (self.tmpdir / "appointments.csv").open("a", encoding="utf-8", newline="") as f:
            csv.writer(f, strict=True).writerow(
                ["k9", "2026-10-17", "I4", "V1", "V2", "", "盲复测", "开放", ""]
            )
        from workbench.io import load_survey

        data = load_survey(self.tmpdir)
        plan = rank_followups(data, "2026-10-14", self.reports, self.estimates)
        self.assertTrue(all(c.slot != "k9" for c in plan.ranked))
        self.assertTrue(any(s["slot"] == "k9" for s in plan.skipped_slots))

    def test_training_readiness_split(self):
        readiness = training_readiness(self.data, self.reports, self.gaps)
        usable = [r for r in readiness if r["training_use"] == "可用于培训分配"]
        pending = [r for r in readiness if r["training_use"] == "仅提示待核实"]
        self.assertEqual(len(usable), 1)
        self.assertEqual(usable[0]["concept"], "总糖")
        self.assertTrue(all("V1->V2" in r["condition"] or "V3->V1" in r["condition"]
                            for r in pending))


if __name__ == "__main__":
    unittest.main()
