"""端到端：新回执按真实邀请设计落表后，重跑必须重新判断。

场景：补访回收一名 V3 主版熟练者的 V1 盲复测，补齐 V3<->V1 锚题 b
（添加）的第 5 个配对且与原版一致，使该锚题从"证据不足"升为"成立"，
随后 添加概念的山城语-普通话差距从"待核实"变为"可用于培训分配"。
"""
import csv
import unittest

from workbench.cli import run_pipeline
from workbench.scales import anchor_equivalence, scale_check

from workbench_case import WorkbenchCase


class NewReceiptTests(WorkbenchCase):
    def test_new_bridge_repair_flips_readiness(self):
        before = self.pipeline()
        before_b = anchor_equivalence(before["data"], "V3", "V1", "b")
        self.assertEqual(before_b.status, "证据不足")
        before_gap = next(
            g for g in before["gaps"]
            if g["concept"] == "添加"
            and {g["language_a"], g["language_b"]} == {"山城语", "普通话"}
        )
        self.assertEqual(before_gap["status"], "尺度未验证")

        # 选一名 V3 主版、熟练、可补访、尚未做过任何桥接，且 q32 原版有观察的受访者
        candidate = None
        for p, inv in sorted(self.data_invitation_items()):
            if not (
                inv.assigned_version == "V3"
                and inv.fluent
                and inv.consent == "可补访"
                and not self._has_bridge(p)
            ):
                continue
            original_q32 = self._original_code(p, "V3", "q32")
            if original_q32 is not None:
                candidate = p
                q32_code = original_q32
                break
        self.assertIsNotNone(candidate)
        q31_code = self._original_code(candidate, "V3", "q31")
        self._append_v1_blind_rows(candidate, q31_code, q32_code)

        after = run_pipeline(self.tmpdir, "2026-10-14")
        after_b = anchor_equivalence(after["data"], "V3", "V1", "b")
        self.assertEqual(after_b.n_pairs, 5)
        self.assertEqual(after_b.status, "成立")

        after_gap = next(
            g for g in after["gaps"]
            if g["concept"] == "添加"
            and {g["language_a"], g["language_b"]} == {"山城语", "普通话"}
        )
        self.assertEqual(after_gap["status"], "可比较")
        readiness = next(
            r for r in after["readiness"]
            if r["concept"] == "添加"
            and {r["language_a"], r["language_b"]} == {"山城语", "普通话"}
        )
        self.assertEqual(readiness["training_use"], "可用于培训分配")
        # 河湾语相关差距仍然不能被"顺带修复"
        self.assertTrue(
            all(
                g["status"] == "尺度未验证"
                for g in after["gaps"]
                if "河湾语" in (g["language_a"], g["language_b"])
            )
        )

    def test_volunteer_interview_answers_never_fill_population_gaps(self):
        # 新增一条"访谈（先看答案）"回执：估计口径必须完全不变
        before = self.pipeline()
        before_points = {
            (e.preferred, e.channel, e.concept): e.point for e in before["estimates"]
        }
        candidate = next(
            p
            for p, inv in sorted(self.data_invitation_items())
            if inv.assigned_version == "V3"
            and inv.fluent
            and inv.consent == "可补访"
            and not self._has_bridge(p)
        )
        with (self.tmpdir / "responses.csv").open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, strict=True)
            writer.writerow(
                [f"r{int(candidate[1:]):03d}c9", candidate, "V3", "q32", "2",
                 "访谈", "1", "2026-10-16"]
            )
        after = run_pipeline(self.tmpdir, "2026-10-14")
        for est in after["estimates"]:
            key = (est.preferred, est.channel, est.concept)
            self.assertAlmostEqual(est.point, before_points[key], places=9)

    # ---- 辅助 ----
    def data_invitation_items(self):
        from workbench.io import load_survey

        data = load_survey(self.tmpdir)
        return data.invitations.items()

    def _has_bridge(self, person: str) -> bool:
        with (self.tmpdir / "responses.csv").open(encoding="utf-8", newline="") as f:
            return any(
                row["person"] == person and row["bridge"] != "原版"
                for row in csv.DictReader(f, strict=True)
            )

    def _original_code(self, person: str, version: str, item: str):
        with (self.tmpdir / "responses.csv").open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, strict=True):
                if (
                    row["person"] == person
                    and row["bridge"] == "原版"
                    and row["version"] == version
                    and row["item"] == item
                    and row["code"] != ""
                ):
                    return row["code"]
        return None

    def _append_v1_blind_rows(self, person: str, q11_code: str, q12_code: str) -> None:
        # V1 锚题：q11（位置1，总糖/a）、q12（位置2，添加/b）；
        # 编码与该人 V3 原版一致，保证新增配对不产生分歧
        with (self.tmpdir / "responses.csv").open("a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, strict=True)
            writer.writerow(
                [f"r{int(person[1:]):03d}b1", person, "V1", "q11", 1,
                 "盲复测", q11_code, "2026-10-15"]
            )
            writer.writerow(
                [f"r{int(person[1:]):03d}b2", person, "V1", "q12", 2,
                 "盲复测", q12_code, "2026-10-15"]
            )


if __name__ == "__main__":
    unittest.main()
