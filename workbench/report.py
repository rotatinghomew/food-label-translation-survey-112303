"""把工作台结果渲染成终端文本与机器可读 JSON。"""
from __future__ import annotations

import math
from dataclasses import asdict, is_dataclass

from .brief import RoundBrief
from .estimates import LanguageRollup, StratumEstimate
from .scheduler import FollowUpCandidate, SlotAssessment


def _fmt(value, digits=3) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "不可计算"
        return f"{value:.{digits}f}"
    return str(value)


def render_scale(reports) -> str:
    lines = ["=== 共同题等值核对 ==="]
    for report in reports:
        lines.append(
            f"\n[{report.version_a} -> {report.version_b}] 设计合格口径：{report.eligible_population}"
            f"（实际覆盖：{'仅熟练' if report.person_fluent_only else '含非熟练'}）"
            f"，盲测人数 {report.n_persons}，顺序效应可分：{'是' if report.separable_order else '否'}"
        )
        if report.observed_orientations:
            lines.append(f"  实际桥接方向：{'、'.join(report.observed_orientations)}")
        if report.note:
            lines.append(f"  说明：{report.note}")
        for rep in report.anchor_reports:
            lines.append(
                f"  - 锚题 {rep.anchor}（{rep.concept}）状态：{rep.status}"
                f"；一致 {rep.n_agree}/{rep.n_pairs}，分歧 {rep.n_disagree}"
                f"（正确->误解 {rep.n_correct_to_wrong}，误解->正确 {rep.n_wrong_to_correct}）"
            )
            lines.append(
                f"    一致率 {_fmt(rep.agree_rate)}，"
                f"Wilson95% [{_fmt(rep.wilson_low)}, {_fmt(rep.wilson_high)}]，"
                f"适用：{rep.applies_to}"
            )
            if rep.note:
                lines.append(f"    备注：{rep.note}")
    return "\n".join(lines)


def render_estimates(estimates: list[StratumEstimate], rollups: list[LanguageRollup]) -> str:
    lines = ["\n=== 分层误解率（仅原版回答，加权口径）==="]
    header = (
        f"{'语言':<6}{'渠道':<6}{'概念':<6}{'有效题次':>8}{'误解证据':>8}"
        f"{'点估计':>10}{'下界':>8}{'上界':>8}  尺度"
    )
    lines.append(header)
    for est in estimates:
        lines.append(
            f"{est.preferred:<6}{est.channel:<6}{est.concept:<6}"
            f"{est.n_observed:>8}{est.n_misconception:>8}"
            f"{_fmt(est.point):>10}{_fmt(est.low_bound):>8}{_fmt(est.high_bound):>8}  "
            f"{est.scale_status}"
        )
    lines.append("\n-- 语言合并（跨渠道按权重）--")
    for roll in rollups:
        lines.append(
            f"{roll.preferred:<6}{roll.concept:<6} 点估计 {_fmt(roll.point)}"
            f"，区间 [{_fmt(roll.low_bound)}, {_fmt(roll.high_bound)}]"
            f"，尺度 {roll.scale_status}"
            + (f"；{'；'.join(roll.notes)}" if roll.notes else "")
        )
    return "\n".join(lines)


def render_brief(brief: RoundBrief, integrity_lines: list[str]) -> str:
    lines = [f"\n=== 轮次简报 {brief.round} ==="]
    for s in brief.strata:
        lines.append(
            f"\n[{s.preferred} / {s.channel}] 合资格 {s.eligible}，"
            f"已接触 {s.contacted}，未接触 {s.never_contacted}，"
            f"已邀请未答 {s.invited_nonresponse}，有效受访者 {s.valid_respondents}"
            + (f"，其中只准分析 {s.analysis_only} 人" if s.analysis_only else "")
        )
        for concept in s.misconception_evidence:
            lo, hi = s.bounds[concept]
            lines.append(
                f"  - {concept}：误解证据 {s.misconception_evidence[concept]} 题次/"
                f"观察 {s.observed_items[concept]}，点估计 {_fmt(s.point[concept])}，"
                f"可能区间 [{_fmt(lo)}, {_fmt(hi)}]，尺度：{s.scale_status[concept]}"
            )
        for note in s.notes:
            lines.append(f"  备注：{note}")
    lines.append("\n-- 撤回影响 --")
    lines.extend(f"  {line}" for line in integrity_lines)
    if brief.deactivations:
        lines.append("\n-- 译版停用 --")
        for version, day in brief.deactivations.items():
            lines.append(f"  {version} 自 {day} 停用；停用日前回答仍为有效证据")
    lines.append("\n-- 可比性结论 --")
    lines.extend(f"  {line}" for line in brief.comparability_summary)
    lines.append("\n-- 跨语言差距 --")
    lines.extend(f"  {line}" for line in brief.gap_summary)
    lines.append("\n-- 适用范围 --")
    lines.extend(f"  {line}" for line in brief.applicability)
    return "\n".join(lines)


def render_slots(assessments: list[SlotAssessment], inventory: dict) -> str:
    lines = ["\n=== 席位与预约检查 ==="]
    for a in assessments:
        flag = "可用" if a.usable and not a.problems else ("锁定" if a.locked else "有问题")
        target = a.person or "（开放）"
        lines.append(
            f"{a.slot} {a.day} {a.interviewer} {a.from_version}->{a.to_version} "
            f"{a.kind} {a.status} {target} -> {flag}"
        )
        for problem in a.problems:
            lines.append(f"  问题：{problem}")
        lines.append(f"  可比性：{a.comparability_note}")
    lines.append("\n-- 各语言尚可用席位 --")
    for lang, bucket in sorted(inventory.items()):
        lines.append(
            f"{lang}：开放 {bucket['open_seats']}，锁定预约 {bucket['booked_locked']}，"
            f"问题预约 {bucket['booked_problem']}，席位 {', '.join(bucket['slots'])}"
        )
    return "\n".join(lines)


def render_candidates(plan, readiness: list[dict]) -> str:
    lines = ["\n=== 补访候选排序（每个开放席位取最高分候选）==="]
    if not plan.ranked:
        lines.append("  没有合规的开放席位候选")
    for c in plan.ranked:
        lines.append(
            f"{c.slot} {c.day} {c.interviewer} {c.from_version}->{c.to_version} "
            f"{c.kind} <- {c.person}（{c.preferred}/{c.channel}），总分 {c.total_score:.3f}"
        )
        for reason in c.reasons:
            lines.append(f"  {reason}")
    lines.append("\n-- 各开放席位合规池规模 --")
    for slot, size in sorted(plan.pool_sizes.items()):
        lines.append(f"  {slot}：{size} 名合规候选人")
    if plan.blocked:
        lines.append("\n-- 硬约束拦截示例（每席位最多列 5 人）--")
        for b in plan.blocked:
            lines.append(f"  {b.slot} {b.person}：{'；'.join(b.blocks)}")
    if plan.skipped_slots:
        lines.append("\n-- 无法派出的席位 --")
        for item in plan.skipped_slots:
            lines.append(f"  {item['slot']}：{item['reason']}")
    lines.append("\n=== 培训可用性 ===")
    for item in readiness:
        lines.append(
            f"{item['concept']} {item['language_a']}-{item['language_b']}："
            f"{item['training_use']}（{item['status']}）"
        )
        lines.append(f"  条件：{item['condition']}")
    return "\n".join(lines)


def to_jsonable(obj):
    if is_dataclass(obj):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj
