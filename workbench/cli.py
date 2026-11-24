"""命令行入口：一个命令生成整份工作台结果，新回执到达后可直接重跑。

用法
----
python -m workbench.cli run --data data --today 2026-10-14 --out outputs
python -m workbench.cli run --data data --today 2026-10-14 --json   # 只出 JSON

设计：所有判定都从传入目录里的六张表重新推导，不缓存任何中间结论，
因此新回执按其真实邀请设计落表后，重跑即可重新判断。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import brief as brief_mod
from . import estimates as est_mod
from . import report as report_mod
from . import scales
from . import scheduler
from .io import load_survey


def run_pipeline(directory: str | Path, today: str, *, withdraw_groups: bool = False) -> dict:
    data = load_survey(directory, withdraw_groups=withdraw_groups)

    # 1. 尺度核对
    scale_reports = scales.scale_check(data)
    supported_pairs = {
        (rep.version_a, rep.version_b, rep.anchor)
        for report in scale_reports
        for rep in report.anchor_reports
        if rep.status == "成立"
    }
    non_anchors = scales.non_anchor_coverage(data)

    # 2. 分层估计与差距
    estimates = est_mod.stratified_estimates(data, supported_pairs)
    rollups = est_mod.rollup_language(estimates)
    gaps = est_mod.cross_language_gaps(data, estimates, supported_pairs)

    # 3. 轮次简报
    round_id = sorted({d.round for d in data.rounds})[0]
    round_brief = brief_mod.build_round_brief(
        data, round_id, estimates, scale_reports, gaps
    )
    integrity = brief_mod.bridge_integrity_after_withdrawal(data)

    # 4. 席位与补访
    assessments = scheduler.assess_appointments(data, today)
    inventory = scheduler.seat_inventory(data, today)
    candidates = scheduler.rank_followups(
        data, today, scale_reports, estimates
    )
    readiness = scheduler.training_readiness(data, scale_reports, gaps)

    return {
        "data": data,
        "scale_reports": scale_reports,
        "non_anchors": non_anchors,
        "estimates": estimates,
        "rollups": rollups,
        "gaps": gaps,
        "round_brief": round_brief,
        "integrity": integrity,
        "assessments": assessments,
        "inventory": inventory,
        "followup_plan": candidates,
        "readiness": readiness,
    }


def render_text(result: dict) -> str:
    parts = [
        report_mod.render_scale(result["scale_reports"]),
        report_mod.render_estimates(result["estimates"], result["rollups"]),
        report_mod.render_brief(result["round_brief"], result["integrity"]),
        report_mod.render_slots(result["assessments"], result["inventory"]),
        report_mod.render_candidates(result["followup_plan"], result["readiness"]),
    ]
    non_anchor_lines = ["\n=== 非锚题覆盖（禁止跨语言补齐）==="]
    for item in result["non_anchors"]:
        non_anchor_lines.append(f"  {item.note}")
    parts.append("\n".join(non_anchor_lines))
    if result["data"].validation_notes:
        parts.append(
            "\n=== 结构校验提示 ===\n"
            + "\n".join(f"  {n}" for n in result["data"].validation_notes)
        )
    return "\n".join(parts)


def build_json(result: dict) -> dict:
    data = result["data"]
    return {
        "validation_notes": data.validation_notes,
        "withdrawn_response_ids": sorted(data.withdrawn_response_ids),
        "deactivated_versions": {
            v: d.isoformat() for v, d in data.deactivated_versions.items()
        },
        "scale_reports": report_mod.to_jsonable(result["scale_reports"]),
        "non_anchor_coverage": report_mod.to_jsonable(result["non_anchors"]),
        "estimates": report_mod.to_jsonable(result["estimates"]),
        "language_rollups": report_mod.to_jsonable(result["rollups"]),
        "cross_language_gaps": report_mod.to_jsonable(result["gaps"]),
        "round_brief": report_mod.to_jsonable(result["round_brief"]),
        "withdrawal_integrity": result["integrity"],
        "slot_assessments": report_mod.to_jsonable(result["assessments"]),
        "seat_inventory": report_mod.to_jsonable(list(result["inventory"].values())),
        "followup_plan": report_mod.to_jsonable(result["followup_plan"]),
        "training_readiness": report_mod.to_jsonable(result["readiness"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="糖标注理解调查工作台")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="跑完整工作台")
    run.add_argument("--data", type=Path, required=True, help="六张 CSV 所在目录")
    run.add_argument("--today", default="2026-10-14", help="判定改期锁使用的当天日期")
    run.add_argument("--out", type=Path, help="输出目录（同时写 txt 与 json）")
    run.add_argument("--json", action="store_true", help="只向标准输出打印 JSON")
    run.add_argument(
        "--withdraw-groups",
        action="store_true",
        help="撤回 target 同时视为整组撤回（默认只撤被点名的行）",
    )
    args = parser.parse_args(argv)

    result = run_pipeline(args.data, args.today, withdraw_groups=args.withdraw_groups)
    payload = build_json(result)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0

    text = render_text(result)
    print(text)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "workbench.txt").write_text(text + "\n", encoding="utf-8")
        (args.out / "workbench.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\n已写出：{args.out / 'workbench.txt'}、{args.out / 'workbench.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
