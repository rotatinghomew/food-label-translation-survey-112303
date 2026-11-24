"""机器可读输出：JSON 可解析、无 NaN，且与流水线结果一致。"""
import json
import unittest

from workbench.cli import build_json
from workbench.report import to_jsonable

from workbench_case import WorkbenchCase


class JsonOutputTests(WorkbenchCase):
    def test_json_payload_is_valid_and_nan_free(self):
        result = self.pipeline()
        payload = build_json(result)
        text = json.dumps(payload, ensure_ascii=False, default=str)
        self.assertNotIn("NaN", text)
        parsed = json.loads(text)  # 抛异常即失败
        self.assertEqual(
            set(parsed),
            {
                "validation_notes",
                "withdrawn_response_ids",
                "deactivated_versions",
                "scale_reports",
                "non_anchor_coverage",
                "estimates",
                "language_rollups",
                "cross_language_gaps",
                "round_brief",
                "withdrawal_integrity",
                "slot_assessments",
                "seat_inventory",
                "followup_plan",
                "training_readiness",
            },
        )

    def test_blocked_gaps_serialize_as_null_not_nan(self):
        result = self.pipeline()
        payload = build_json(result)
        blocked = [
            g for g in payload["cross_language_gaps"] if g["status"] == "尺度未验证"
        ]
        self.assertTrue(blocked)
        for gap in blocked:
            self.assertIsNone(gap["gap"])
            self.assertIsNone(gap["low"])
            self.assertIsNone(gap["high"])

    def test_to_jsonable_handles_dataclasses_and_sets(self):
        result = self.pipeline()
        blob = to_jsonable(result["followup_plan"])
        self.assertEqual(set(blob), {"ranked", "blocked", "pool_sizes", "skipped_slots"})
        self.assertIsInstance(blob["pool_sizes"], dict)


if __name__ == "__main__":
    unittest.main()
