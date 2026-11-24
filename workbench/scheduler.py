"""补访席位与预约：冲突检查、停用影响、补访优先级。

硬约束（违反即不可排）
----------------------
1. 同一受访者不能同时占用"盲复测"和"已展示答案的访谈"——盲测一旦先看答案
   就失去独立测量意义。历史上已完成的两类回答只做记录，新预约必须拦截。
2. 盲复测/访谈桥接只对 rounds.csv 声明的桥接合格人群开放（本数据即熟练读者）；
   给非熟练者排桥接属于设计破坏，标记为"资格不符"。
3. 已预约且未到允许改期日（rebook_after）的席位继续占用原访员，不得改派。
4. 译版停用后，任何指向该版的新安排都不能按原设计执行；保留还是改派要分别
   说明对可比性的影响。
5. 只准分析（consent=只准分析）的受访者不能进入补访候选。

优先级（在硬约束通过后排序）
----------------------------
* 关键题连接修复：补的是当前等值"失败/证据不足"的版本对与锚题；
* 总体估计摇摆：该语言×渠道×概念的边界宽度（high-low）越大越优先；
* 桥接稀缺：该版本对现有盲测人数越少越优先。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .io import (
    BRIDGE_BLIND,
    BRIDGE_SHOWN,
    CONSENT_REVISIT,
    SLOT_BOOKED,
    SLOT_OPEN,
    SurveyData,
)


@dataclass
class SlotAssessment:
    slot: str
    day: str
    interviewer: str
    from_version: str
    to_version: str
    person: str
    kind: str
    status: str
    rebook_after: str | None
    problems: list[str] = field(default_factory=list)
    comparability_note: str = ""
    usable: bool = True
    locked: bool = False          # 未到改期日，继续占用原访员
    uses_deactivated: bool = False


@dataclass
class FollowUpCandidate:
    person: str
    preferred: str
    channel: str
    slot: str
    interviewer: str
    kind: str
    from_version: str
    to_version: str
    day: str
    anchor_repair_score: float
    estimate_instability_score: float
    scarcity_score: float
    total_score: float
    reasons: list[str] = field(default_factory=list)
    eligible: bool = True
    blocks: list[str] = field(default_factory=list)


@dataclass
class BlockedCandidate:
    slot: str
    person: str
    blocks: list[str]


@dataclass
class FollowUpPlan:
    ranked: list[FollowUpCandidate]          # 每个开放席位只保留最高分候选
    blocked: list[BlockedCandidate]          # 被硬约束拦下的典型（每席位最多 5 个）
    pool_sizes: dict[str, int]               # 每个开放席位的合规候选人数
    skipped_slots: list[dict]                # 无候选或指向停用版的席位


def _has_completed(data: SurveyData, person: str, bridge: str) -> bool:
    return any(
        r.person == person and r.bridge == bridge and not r.withdrawn
        for r in data.active_responses()
    )


def assess_appointments(data: SurveyData, today: str) -> list[SlotAssessment]:
    """逐个席位给出资格、停用、改期锁与可比性判断。"""
    from datetime import date

    today_d = date.fromisoformat(today)
    deactivated = data.deactivated_versions
    out: list[SlotAssessment] = []
    for appt in sorted(data.appointments, key=lambda a: a.slot):
        problems: list[str] = []
        locked = False
        uses_dead = appt.to_version in deactivated or appt.from_version in deactivated
        if appt.status == SLOT_BOOKED:
            if appt.rebook_after is not None and today_d < appt.rebook_after:
                locked = True
                problems.append(
                    f"未到允许改期日 {appt.rebook_after}，席位继续由 {appt.interviewer} 占用"
                )
            invitation = data.invitations.get(appt.person)
            if invitation is None:
                problems.append("预约人不在邀请框内")
            else:
                if not invitation.bridge_eligible:
                    problems.append(
                        f"{appt.person} 无桥接资格（非熟练/未入桥接抽样），"
                        "该预约破坏桥接设计"
                    )
                if invitation.consent != CONSENT_REVISIT:
                    problems.append(f"{appt.person} 授权为{invitation.consent}，不可补访")
                # 硬约束 1：同受访者两类桥接互斥
                other = BRIDGE_SHOWN if appt.kind == BRIDGE_BLIND else BRIDGE_BLIND
                if _has_completed(data, appt.person, other):
                    problems.append(
                        f"{appt.person} 已完成{other}，不能再排{appt.kind}"
                    )
        if uses_dead:
            dead_version = appt.to_version if appt.to_version in deactivated else appt.from_version
            problems.append(
                f"{dead_version} 已于 {deactivated[dead_version].isoformat()} 停用"
            )

        note = _comparability_note(data, appt, uses_dead)
        out.append(
            SlotAssessment(
                slot=appt.slot,
                day=appt.day.isoformat(),
                interviewer=appt.interviewer,
                from_version=appt.from_version,
                to_version=appt.to_version,
                person=appt.person,
                kind=appt.kind,
                status=appt.status,
                rebook_after=appt.rebook_after.isoformat() if appt.rebook_after else None,
                problems=problems,
                comparability_note=note,
                usable=not problems or locked,
                locked=locked,
                uses_deactivated=uses_dead,
            )
        )
    return out


def _comparability_note(data: SurveyData, appt, uses_dead: bool) -> str:
    if uses_dead:
        return (
            f"若按原设计执行，只能取得停用版的最后一批证据，不可作为新常规；"
            f"若改派到仍启用的版本对，{appt.from_version}->{appt.to_version} 这条"
            "可比关系不会得到新增样本，既有缺口保留"
        )
    if appt.from_version == appt.to_version:
        return (
            f"同版 {appt.from_version} 的{appt.kind}不产生跨语言桥接，"
            "只能补充该译版内部的题间连接与缺失题次，不能修复跨版等值关系"
        )
    return (
        f"保持原设计：{appt.from_version}->{appt.to_version} 的{appt.kind} "
        "可继续修复该版本对的共同题连接"
    )


def seat_inventory(data: SurveyData, today: str) -> dict:
    """按目标语言（to_version 对应语言）汇总尚可用席位。"""
    assessments = assess_appointments(data, today)
    version_language = {d.default_version: d.preferred for d in data.rounds}
    inventory: dict[str, dict] = {}
    for a in assessments:
        lang = version_language.get(a.to_version, a.to_version)
        bucket = inventory.setdefault(
            lang,
            {"language": lang, "open_seats": 0, "booked_locked": 0, "booked_problem": 0, "slots": []},
        )
        bucket["slots"].append(a.slot)
        if a.status == SLOT_OPEN and not a.uses_deactivated:
            bucket["open_seats"] += 1
        elif a.status == SLOT_BOOKED and a.locked:
            bucket["booked_locked"] += 1
        elif a.problems:
            bucket["booked_problem"] += 1
    return inventory


def _undirected(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


def evaluate_slot_candidates(
    data: SurveyData, appt, done_blind: set[str], done_shown: set[str]
) -> tuple[list[tuple], list[BlockedCandidate]]:
    """对单个席位枚举候选人，返回 (合规候选, 被拦截记录)。

    供补访排序与冲突复核共用；拦截原因保留硬约束的完整语义。
    """
    pool: list[tuple] = []
    blocked: list[BlockedCandidate] = []
    for person, inv in sorted(data.invitations.items()):
        blocks: list[str] = []
        if not inv.bridge_eligible or not inv.fluent:
            blocks.append("非桥接合格人群（熟练限定）")
        if inv.consent != CONSENT_REVISIT:
            blocks.append("授权只准分析，不可补访")
        if inv.assigned_version != appt.from_version:
            blocks.append(
                f"主版 {inv.assigned_version} 与席位 {appt.from_version} 不符"
            )
        if appt.kind == BRIDGE_BLIND and person in done_shown:
            blocks.append("已做过展示答案访谈，不能再盲复测")
        if appt.kind == BRIDGE_SHOWN and person in done_blind:
            blocks.append("已做过盲测，不能再安排展示答案访谈")
        if blocks:
            if len([b for b in blocked if b.slot == appt.slot]) < 5:
                blocked.append(BlockedCandidate(appt.slot, person, blocks))
            continue
        pool.append((person, inv))
    return pool, blocked


def rank_followups(
    data: SurveyData,
    today: str,
    scale_reports,
    estimates,
) -> FollowUpPlan:
    """对开放席位枚举合规候选人并打分；已预约席位只做占用说明，不重新派位。

    每个开放席位只输出最高分的一名候选人（席位本身只有一个），被硬约束
    拦下的人按席位抽样记录原因，供调查组人工复核边界情况。
    同版访谈不产生跨语言桥接：硬约束照常体检，但不进入连接修复排序。
    """
    # 1. 每个版本对（无向）当前锚题状态 -> 修复分
    pair_need: dict[frozenset[str], float] = {}
    pair_persons: dict[frozenset[str], int] = {}
    for report in scale_reports:
        key = _undirected(report.version_a, report.version_b)
        pair_persons[key] = report.n_persons
        need = 0.0
        for rep in report.anchor_reports:
            if rep.status == "失败":
                need += 1.0
            elif rep.status == "证据不足":
                need += 0.6
            if rep.order_confounded:
                need += 0.2
        pair_need[key] = need

    # 2. 语言×概念的边界宽度（估计摇摆度，按概念取平均后汇总到语言）
    instability: dict[str, float] = {}
    concept_count = len({est.concept for est in estimates})
    per_language: dict[str, list[float]] = {}
    for est in estimates:
        per_language.setdefault(est.preferred, []).append(est.high_bound - est.low_bound)
    for lang, widths in per_language.items():
        instability[lang] = sum(widths) / max(1, concept_count)

    # 3. 已完成任一桥接的人不能再排互斥桥接
    done_blind = {
        r.person for r in data.active_responses() if r.bridge == BRIDGE_BLIND
    }
    done_shown = {
        r.person for r in data.active_responses() if r.bridge == BRIDGE_SHOWN
    }

    version_language = {d.default_version: d.preferred for d in data.rounds}
    ranked: list[FollowUpCandidate] = []
    blocked: list[BlockedCandidate] = []
    pool_sizes: dict[str, int] = {}
    skipped: list[dict] = []

    for appt in sorted(data.appointments, key=lambda a: a.slot):
        if appt.status != SLOT_OPEN:
            continue
        if appt.to_version in data.deactivated_versions:
            skipped.append(
                {
                    "slot": appt.slot,
                    "reason": f"目标译版 {appt.to_version} 已停用，开放席位不能按原设计派出",
                }
            )
            continue
        pool, slot_blocks = evaluate_slot_candidates(
            data, appt, done_blind, done_shown
        )
        blocked.extend(slot_blocks)
        # 同版访谈不产生跨语言桥接：硬约束照常体检，但不进入连接修复排序
        if appt.from_version == appt.to_version:
            pool_sizes[appt.slot] = len(pool)
            skipped.append(
                {
                    "slot": appt.slot,
                    "reason": (
                        f"{appt.from_version}->{appt.to_version} 为同版访谈，"
                        "不产生跨语言桥接，无法修复关键题间连接，仅可作本版补题资源"
                    ),
                }
            )
            continue
        key = _undirected(appt.from_version, appt.to_version)
        target_lang = version_language.get(appt.to_version, "")
        slot_candidates: list[FollowUpCandidate] = []
        for person, inv in pool:
            repair = pair_need.get(key, 0.0)
            instab = instability.get(target_lang, 0.0)
            scarcity = 1.0 / (1.0 + pair_persons.get(key, 0))
            score = repair + instab + scarcity
            slot_candidates.append(
                FollowUpCandidate(
                    person=person,
                    preferred=inv.preferred,
                    channel=inv.channel,
                    slot=appt.slot,
                    interviewer=appt.interviewer,
                    kind=appt.kind,
                    from_version=appt.from_version,
                    to_version=appt.to_version,
                    day=appt.day.isoformat(),
                    anchor_repair_score=repair,
                    estimate_instability_score=instab,
                    scarcity_score=scarcity,
                    total_score=score,
                    reasons=[
                        f"版本对 {appt.from_version}<->{appt.to_version} 修复需求 {repair:.1f}",
                        f"{target_lang} 估计边界宽度合计 {instab:.3f}",
                        f"该桥接现有 {pair_persons.get(key, 0)} 人，稀缺分 {scarcity:.2f}",
                    ],
                )
            )
        pool_sizes[appt.slot] = len(slot_candidates)
        if not slot_candidates:
            skipped.append({"slot": appt.slot, "reason": "没有满足全部硬约束的候选人"})
            continue
        slot_candidates.sort(key=lambda c: (-c.total_score, c.person))
        ranked.append(slot_candidates[0])

    ranked.sort(key=lambda c: (-c.total_score, c.slot))
    return FollowUpPlan(
        ranked=ranked,
        blocked=blocked,
        pool_sizes=pool_sizes,
        skipped_slots=skipped,
    )


def training_readiness(
    data: SurveyData,
    scale_reports,
    gaps: list[dict],
) -> list[dict]:
    """区分哪些差距终于能用于分配培训，哪些只适合提示待核实。"""
    out: list[dict] = []
    for gap in gaps:
        if gap["status"] == "可比较":
            out.append(
                {
                    **gap,
                    "training_use": "可用于培训分配",
                    "condition": "等值桥接成立，且桥接覆盖人群与培训对象一致（熟练读者）",
                }
            )
        else:
            failed_anchors = [
                f"{r.version_a}->{r.version_b}/{rep.anchor}={rep.status}"
                for r in scale_reports
                for rep in r.anchor_reports
                if rep.status != "成立"
            ]
            out.append(
                {
                    **gap,
                    "training_use": "仅提示待核实",
                    "condition": "；".join(failed_anchors) or "缺少桥接样本",
                }
            )
    return out
