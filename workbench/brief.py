"""轮次简报：按偏好语言×渠道汇总框、回答、两类误解证据与缺口。

一份简报必须同时回答：
1. 涉及多少合资格人、实际接触多少、有效回答多少；
2. "总糖"误解与"没有额外加入某一种糖（添加）"误解各有多少证据；
3. 缺口里多少是"已邀请未答"、多少是"根本未接触"；
4. 撤回削弱了哪些可比关系，哪些单独估计仍然成立；
5. 哪些组合/比较满足同一总体、可比尺度，哪些只能给高/低估范围。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .io import BRIDGE_BLIND, BRIDGE_ORIGINAL, BRIDGE_SHOWN, SurveyData
from .estimates import StratumEstimate
from .scales import BridgeReport


@dataclass
class StratumBrief:
    round: str
    preferred: str
    channel: str
    eligible: int
    contacted: int
    never_contacted: int
    invited_nonresponse: int
    valid_respondents: int
    analysis_only: int
    misconception_evidence: dict[str, int]   # concept -> 误解证据题次
    observed_items: dict[str, int]
    point: dict[str, float]
    bounds: dict[str, tuple[float, float]]
    scale_status: dict[str, str]
    notes: list[str] = field(default_factory=list)


@dataclass
class RoundBrief:
    round: str
    strata: list[StratumBrief]
    withdrawals: list[str]
    deactivations: dict[str, str]
    bridge_reports: list[BridgeReport]
    comparability_summary: list[str]
    gap_summary: list[str]
    applicability: list[str]


def _respondent_set(data: SurveyData) -> set[str]:
    return {
        r.person
        for r in data.active_responses()
        if r.bridge == BRIDGE_ORIGINAL
    }


def build_round_brief(
    data: SurveyData,
    round_id: str,
    estimates: list[StratumEstimate],
    scale_reports: list[BridgeReport],
    gaps: list[dict],
) -> RoundBrief:
    respondents = _respondent_set(data)
    est_index = {(e.preferred, e.channel, e.concept): e for e in estimates}
    strata_keys = sorted(
        {(inv.preferred, inv.channel) for inv in data.invitations.values()
         if inv.round == round_id}
    )
    strata_briefs: list[StratumBrief] = []
    for preferred, channel in strata_keys:
        persons = [
            p
            for p, inv in data.invitations.items()
            if inv.round == round_id and inv.preferred == preferred and inv.channel == channel
        ]
        contacted = [p for p in persons if data.invitations[p].contacted]
        never = len(persons) - len(contacted)
        nonresp = sum(1 for p in contacted if p not in respondents)
        valid = sum(1 for p in persons if p in respondents)
        analysis_only = sum(
            1 for p in persons if data.invitations[p].consent == "只准分析"
        )
        evidence: dict[str, int] = {}
        observed: dict[str, int] = {}
        points: dict[str, float] = {}
        bounds: dict[str, tuple[float, float]] = {}
        statuses: dict[str, str] = {}
        notes: list[str] = []
        for concept in data.concepts:
            est = est_index[(preferred, channel, concept)]
            evidence[concept] = est.n_misconception
            observed[concept] = est.n_observed
            points[concept] = est.point
            bounds[concept] = (est.low_bound, est.high_bound)
            statuses[concept] = est.scale_status
            notes.extend(est.notes)
        strata_briefs.append(
            StratumBrief(
                round=round_id,
                preferred=preferred,
                channel=channel,
                eligible=len(persons),
                contacted=len(contacted),
                never_contacted=never,
                invited_nonresponse=nonresp,
                valid_respondents=valid,
                analysis_only=analysis_only,
                misconception_evidence=evidence,
                observed_items=observed,
                point=points,
                bounds=bounds,
                scale_status=statuses,
                notes=sorted(set(notes)),
            )
        )

    comparability = _comparability_summary(scale_reports)
    gap_lines = _gap_summary(gaps)
    applicability = _applicability_lines(data, scale_reports)
    withdrawals = sorted(data.withdrawn_response_ids)
    deactivations = {v: d.isoformat() for v, d in data.deactivated_versions.items()}
    return RoundBrief(
        round=round_id,
        strata=strata_briefs,
        withdrawals=withdrawals,
        deactivations=deactivations,
        bridge_reports=scale_reports,
        comparability_summary=comparability,
        gap_summary=gap_lines,
        applicability=applicability,
    )


def _comparability_summary(reports: list[BridgeReport]) -> list[str]:
    lines: list[str] = []
    for report in reports:
        for rep in report.anchor_reports:
            lines.append(
                f"{rep.version_a}->{rep.version_b} 锚题 {rep.anchor}"
                f"（{rep.concept}）：{rep.status}，"
                f"一致 {rep.n_agree}/{rep.n_pairs}，"
                f"Wilson95% [{rep.wilson_low:.3f}, {rep.wilson_high:.3f}]，"
                f"适用 {rep.applies_to}"
                + (f"；{rep.note}" if rep.note else "")
            )
    return lines


def _gap_summary(gaps: list[dict]) -> list[str]:
    lines = []
    for gap in gaps:
        if gap["status"] == "可比较":
            lines.append(
                f"{gap['concept']}：{gap['language_a']}-{gap['language_b']} "
                f"差距 {gap['gap']:+.3f}（区间 {gap['low']:+.3f} 到 {gap['high']:+.3f}），"
                "可进入培训分配"
            )
        else:
            lines.append(
                f"{gap['concept']}：{gap['language_a']}-{gap['language_b']} "
                "尺度未验证，只提示待核实——" + gap["note"]
            )
    return lines


def _applicability_lines(data: SurveyData, reports: list[BridgeReport]) -> list[str]:
    lines: list[str] = []
    for report in reports:
        if report.person_fluent_only:
            lines.append(
                f"{report.version_a}->{report.version_b} 桥接只覆盖熟练读者"
                f"（{report.n_persons} 人），等值结论与跨语言差距只适用熟练人群，"
                "非熟练人群的单独估计仍有效但不可外推桥接结论"
            )
        if not report.separable_order:
            lines.append(
                f"{report.version_a}->{report.version_b} 的顺序与译版效应无法分开，"
                "培训材料不能把该版本对上的分歧单独归因于译文"
            )
    # 无桥接语言：该语言主版虽出现在某个版本对上，但实际盲测受访者里没有
    # 本语言邀请框的人（河湾语全员非熟练，而盲测只抽熟练者，正是这种情况）。
    blind_persons_by_language: dict[str, set[str]] = {}
    for row in data.active_responses():
        if row.bridge == "盲复测":
            preferred = data.invitations[row.person].preferred
            blind_persons_by_language.setdefault(preferred, set()).add(row.person)
    for design in data.rounds:
        own_blind = blind_persons_by_language.get(design.preferred, set())
        if not own_blind:
            lines.append(
                f"{design.preferred}（{design.default_version}）没有覆盖本语言合格人群"
                "的桥接样本：本语言误解率的单独估计有效，但所有跨语言差距均无桥接支撑，"
                "不能由其他语言的题强行补齐"
            )
    return lines


def bridge_integrity_after_withdrawal(data: SurveyData) -> list[str]:
    """撤回影响：逐版本对说明哪些关系被削弱、哪些单独估计仍成立。"""
    lines: list[str] = []
    if not data.withdrawn_response_ids:
        return ["本轮无撤回"]
    # 撤回落在哪些桥接批次
    withdrawn_rows = [r for r in data.responses if r.withdrawn]
    for row in withdrawn_rows:
        invitation = data.invitations[row.person]
        lines.append(
            f"撤回 {row.response}（{row.person}，{invitation.preferred}，"
            f"{row.version}/{row.item}，{row.bridge}）：该人该批次的桥接配对减少，"
            f"但其 {BRIDGE_ORIGINAL} 回答未撤回，{invitation.preferred} 的本语言"
            "单独估计不受影响"
        )
    # 仍有盲测/展示回答的语言单独估计
    versions_with_original = {
        r.version for r in data.active_responses() if r.bridge == BRIDGE_ORIGINAL
    }
    lines.append(
        "仍有原版回答的译版 "
        + "、".join(sorted(versions_with_original))
        + "：各自的分层误解估计继续有效；撤回只削弱桥接关系，不取消单独估计"
    )
    return lines
