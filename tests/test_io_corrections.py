"""io 层：撤回、停用与结构校验。"""
import unittest

from workbench.io import (
    BRIDGE_BLIND,
    DEACTIVATE_KIND,
    WITHDRAW_KIND,
    load_survey,
)

from workbench_case import WorkbenchCase


class CorrectionTests(WorkbenchCase):
    def test_withdrawn_row_excluded_but_siblings_kept_by_default(self):
        data = self.load()
        withdrawn = {r.response for r in data.responses if r.withdrawn}
        # 默认只撤被点名的 r012b1，同组 r012b2/r012b3 仍保留
        self.assertEqual(withdrawn, {"r012b1"})
        active_ids = {r.response for r in data.active_responses()}
        self.assertNotIn("r012b1", active_ids)
        self.assertIn("r012b2", active_ids)
        self.assertIn("r012b3", active_ids)
        # 原版回答完全不受影响
        self.assertTrue(
            all(not r.withdrawn for r in data.responses if r.bridge == "原版")
        )

    def test_withdraw_group_mode_removes_whole_batch(self):
        data = self.load(withdraw_groups=True)
        withdrawn = {r.response for r in data.responses if r.withdrawn}
        self.assertEqual(withdrawn, {"r012b1", "r012b2", "r012b3"})

    def test_deactivation_does_not_delete_history(self):
        data = self.load()
        self.assertIn("V2", data.deactivated_versions)
        v2_rows = [r for r in data.responses if r.version == "V2"]
        self.assertTrue(v2_rows)  # 历史回答仍在
        # 停用不触发撤回：V2 行里除被点名撤回的 r012b1 外都保持有效
        self.assertTrue(
            all(not r.withdrawn for r in v2_rows if r.response != "r012b1")
        )

    def test_unknown_withdrawal_target_raises(self):
        self.write_csv(
            "corrections.csv",
            ["change", "day", "kind", "target"],
            [["c99", "2026-10-12", WITHDRAW_KIND, "r999b1"]],
        )
        with self.assertRaises(ValueError):
            self.load()

    def test_bridge_without_eligibility_rejected(self):
        # 把一个非熟练者的回答改成桥接，必须触发结构校验
        rows = self._read_responses()
        for row in rows:
            if row[0] == "r002a1":
                row[5] = BRIDGE_BLIND
        self._write_responses(rows)
        with self.assertRaises(ValueError):
            self.load()

    def test_original_version_must_match_assignment(self):
        rows = self._read_responses()
        for row in rows:
            if row[0] == "r001a1":
                row[2] = "V3"
        self._write_responses(rows)
        with self.assertRaises(ValueError):
            self.load()

    def test_unknown_deactivation_target_raises(self):
        self.write_csv(
            "corrections.csv",
            ["change", "day", "kind", "target"],
            [["c99", "2026-10-13", DEACTIVATE_KIND, "V9"]],
        )
        with self.assertRaises(ValueError):
            self.load()

    def test_bridge_probability_self_consistency(self):
        data = self.load()
        for inv in data.invitations.values():
            if inv.bridge_eligible:
                self.assertIsNotNone(inv.bridge_p)
            else:
                self.assertIsNone(inv.bridge_p)

    def test_orphan_response_rejected(self):
        rows = self._read_responses()
        rows.append(["r999a1", "p999", "V1", "q11", "1", "原版", "1", "2026-10-03"])
        self._write_responses(rows)
        with self.assertRaises(ValueError):
            self.load()

    def test_illegal_code_rejected(self):
        rows = self._read_responses()
        for row in rows[1:]:
            if row[0] == "r001a1":
                row[6] = "9"
        self._write_responses(rows)
        with self.assertRaises(ValueError):
            self.load()

    def test_duplicate_response_id_rejected(self):
        rows = self._read_responses()
        dup = list(rows[1])
        dup[1] = "p002"
        rows.append(dup)
        self._write_responses(rows)
        with self.assertRaises(ValueError):
            self.load()

    # ---- 辅助 ----
    def _read_responses(self) -> list[list[str]]:
        import csv

        with (self.tmpdir / "responses.csv").open(encoding="utf-8", newline="") as f:
            return list(csv.reader(f, strict=True))

    def _write_responses(self, rows: list[list[str]]) -> None:
        import csv

        with (self.tmpdir / "responses.csv").open("w", encoding="utf-8", newline="") as f:
            csv.writer(f, strict=True).writerows(rows)


if __name__ == "__main__":
    unittest.main()
