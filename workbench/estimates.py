"""分层估计：更新两类误解比例，并在支持不足时给出高/低估边界。

口径
----
* 估计单位是"邀请框中的合格受访者"，权重为 1/selection_p（分层抽取概率）。
  同一渠道内概率恒定，因此层内加权率与未加权率数值相同；跨渠道合并必须加权。
* 只有"原版"回答进入总体估计。盲复测用于等值核对，"访谈"组已先看答案，
  二者都不是独立的总体测量，一律不进入估计。
* 撤回的回答不进入分子分母；逐题缺失在该题上视为未观察。
* 河湾语（V2）没有任何熟练桥接样本：V2 的锚题可做本语言单独估计，
  但任何与 V1/V3 的跨语言差距都标注"尺度未验证"，不强行比较。
* 边界（区间）按"已邀请未答 + 题项缺失"两种未观察分别构造：
  - 下界：所有未观察者都正确（误解=1）；
  - 上界：所有未观察者都误解（误解=0）。
  未接触者属于另一个框，单独报告，不塞进同一组边界冒充无偏区间。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .io import (
    BRIDGE_ORIGINAL,
    CODE_CORRECT,
    CODE_MISCONCEPTION,
    CONSENT_ANALYSIS_ONLY,
    SurveyData,
)


@dataclass
class StratumEstimate:
    round: str
    preferred: str
    channel: str
    concept: str
    items: tuple[str, ...]
    # 框规模
    n_frame: int                     # 该层邀请框人数
    n_contacted: int                 # 实际发出邀请人数
    n_never_contacted: int
    n_invited_nonresponse: int       # 已邀请但无有效原版回答
    n_analysis_only: int             # 只准分析（估计照算，补访不可触达）
    # 逐题证据
    n_administered: int              # 应答题次（有原版记录且未撤回）
    n_observed: int                  # 实际编码题次
    n_missing_items: int
    n_misconception: int             # code=0 的证据题次
    n_correct: int
    # 加权量
    weight_sum: float
    weighted_misconception: float
    weighted_observed: float
    weighted_unobserved: float       # 已接触框内未观察题次的权重（未答者+缺失）
    point: float                     # 加权误解率
    low_bound: float                 # 未观察全对
    high_bound: float                # 未观察全误解
    # 可比性
    comparable_versions: tuple[str, ...]   # 该概念锚题等值成立的译版
    scale_status: str                # 可比 / 仅本译版（他版有桥接）/ 无桥接支撑
    notes: list[str] = field(default_factory=list)


@dataclass
class LanguageRollup:
    preferred: str
    concept: str
    point: float
    low_bound: float
    high_bound: float
    weighted_n: float
    channels: tuple[str, ...]
    scale_status: str
    notes: list[str] = field(default_factory=list)


def _strata(data: SurveyData) -> list[tuple[str, str, str]]:
    keys = {
        (inv.round, inv.preferred, inv.channel)
        for inv in data.invitations.values()
    }
    return sorted(keys)


def _concept_items(data: SurveyData, version: str, concept: str) -> tuple[str, ...]:
    return tuple(
        it.item
        for it in sorted(
            (x for x in data.version_items(version) if x.concept == concept),
            key=lambda x: x.position,
        )
    )


def _version_scale_map(data: SurveyData, supported_pairs: set[tuple[str, str, str]]):
    """concept -> set[version]：锚题等值成立所连通的译版集合。"""
    connected: dict[str, set[str]] = {}
    for va, vb, anchor in supported_pairs:
        item_a = data.anchors[anchor][va]
        connected.setdefault(item_a.concept, set()).update((va, vb))
    return connected


def stratified_estimates(
    data: SurveyData, supported_pairs: set[tuple[str, str, str]]
) -> list[StratumEstimate]:
    """supported_pairs: {(version_a, version_b, anchor)} 等值成立的桥接关系。"""
    connected = _version_scale_map(data, supported_pairs)
    # 每个语言主版
    main_version = {
        (d.round, d.preferred): d.default_version for d in data.rounds
    }
    # 预索引：person -> (concept) -> 原版逐题编码（含缺失标记）
    original_rows: dict[str, list] = {}
    for row in data.active_responses():
        if row.bridge == BRIDGE_ORIGINAL:
            original_rows.setdefault(row.person, []).append(row)
    respondents = set(original_rows)

    out: list[StratumEstimate] = []
    for round_id, preferred, channel in _strata(data):
        persons = [
            p
            for p, inv in sorted(data.invitations.items())
            if inv.round == round_id and inv.preferred == preferred and inv.channel == channel
        ]
        version = main_version[(round_id, preferred)]
        n_frame = len(persons)
        n_contacted = sum(1 for p in persons if data.invitations[p].contacted)
        n_never = n_frame - n_contacted
        n_nonresp = sum(1 for p in persons if data.invitations[p].contacted and p not in respondents)
        n_analysis_only = sum(
            1 for p in persons if data.invitations[p].consent == CONSENT_ANALYSIS_ONLY
        )

        for concept in data.concepts:
            items = _concept_items(data, version, concept)
            n_admin = n_obs = n_mis = n_correct = n_missing = 0
            w_sum = w_obs = w_mis = 0.0
            for person in persons:
                inv = data.invitations[person]
                w = 1.0 / inv.selection_p
                rows = [
                    r
                    for r in original_rows.get(person, [])
                    if (r.version, r.item) in {(version, q) for q in items}
                ]
                if not rows:
                    continue  # 未答者整人未观察，计入缺口而非题次
                w_sum += w
                for row in rows:
                    n_admin += 1
                    if row.code == "":
                        n_missing += 1
                        continue
                    n_obs += 1
                    w_obs += w
                    if row.code == CODE_MISCONCEPTION:
                        n_mis += 1
                        w_mis += w
                    elif row.code == CODE_CORRECT:
                        n_correct += 1
            point = w_mis / w_obs if w_obs else math.nan

            # 边界：未观察 = 已邀请未答者应答题次 + 题项缺失（按其权重计）
            w_unobs_missing = 0.0
            for person in persons:
                inv = data.invitations[person]
                if not inv.contacted or person not in respondents:
                    continue
                w = 1.0 / inv.selection_p
                rows = [
                    r
                    for r in original_rows.get(person, [])
                    if (r.version, r.item) in {(version, q) for q in items}
                ]
                if rows:
                    w_unobs_missing += w * sum(1 for r in rows if r.code == "")
            w_nonresp = sum(
                1.0 / data.invitations[p].selection_p
                for p in persons
                if data.invitations[p].contacted and p not in respondents
            ) * len(items)
            w_denom = w_obs + w_unobs_missing + w_nonresp
            low = w_mis / w_denom if w_denom else math.nan
            high = (w_mis + w_unobs_missing + w_nonresp) / w_denom if w_denom else math.nan
            w_unobserved = w_unobs_missing + w_nonresp

            comparable = tuple(sorted(connected.get(concept, set())))
            if version in connected.get(concept, set()):
                scale_status = "可比"
            elif connected.get(concept):
                # 其他译版之间有成立桥接，但本译版没被连通
                scale_status = "仅本译版"
            else:
                # 该概念当前没有任何成立的等值桥接（区别于"桥接失败"）
                scale_status = "无桥接支撑"
            notes: list[str] = []
            if scale_status != "可比":
                notes.append(
                    f"{concept} 在 {version} 上无成立的等值桥接，"
                    "只能报告本译版单独估计，跨语言差距不得直接相减"
                )
            if n_never:
                notes.append(
                    f"{n_never} 名未接触者在另一邀请框，边界只覆盖已接触框，勿并入无偏区间"
                )

            out.append(
                StratumEstimate(
                    round=round_id,
                    preferred=preferred,
                    channel=channel,
                    concept=concept,
                    items=items,
                    n_frame=n_frame,
                    n_contacted=n_contacted,
                    n_never_contacted=n_never,
                    n_invited_nonresponse=n_nonresp,
                    n_analysis_only=n_analysis_only,
                    n_administered=n_admin,
                    n_observed=n_obs,
                    n_missing_items=n_missing,
                    n_misconception=n_mis,
                    n_correct=n_correct,
                    weight_sum=w_sum,
                    weighted_misconception=w_mis,
                    weighted_observed=w_obs,
                    weighted_unobserved=w_unobserved,
                    point=point,
                    low_bound=low,
                    high_bound=high,
                    comparable_versions=comparable,
                    scale_status=scale_status,
                    notes=notes,
                )
            )
    return out


def rollup_language(estimates: list[StratumEstimate]) -> list[LanguageRollup]:
    """同语言、同概念跨渠道按权重合并；只有尺度状态相同才允许合并展示。"""
    out: list[LanguageRollup] = []
    groups: dict[tuple[str, str], list[StratumEstimate]] = {}
    for est in estimates:
        groups.setdefault((est.preferred, est.concept), []).append(est)
    for (preferred, concept), rows in sorted(groups.items()):
        w_obs = sum(r.weighted_observed for r in rows)
        w_mis = sum(r.weighted_misconception for r in rows)
        w_unobs = sum(r.weighted_unobserved for r in rows)
        w_denom = w_obs + w_unobs
        point = w_mis / w_obs if w_obs else math.nan
        low = w_mis / w_denom if w_denom else math.nan
        high = (w_mis + w_unobs) / w_denom if w_denom else math.nan
        statuses = {r.scale_status for r in rows}
        status = next(iter(statuses)) if len(statuses) == 1 else "仅本译版"
        notes: list[str] = []
        if len(statuses) > 1:
            notes.append("渠道间尺度状态不一致，合并值仅作描述，比较以渠道层为准")
        out.append(
            LanguageRollup(
                preferred=preferred,
                concept=concept,
                point=point,
                low_bound=low,
                high_bound=high,
                weighted_n=w_obs,
                channels=tuple(sorted({r.channel for r in rows})),
                scale_status=status,
                notes=notes,
            )
        )
    return out


def cross_language_gaps(
    data: SurveyData,
    estimates: list[StratumEstimate],
    supported_pairs: set[tuple[str, str, str]],
) -> list[dict]:
    """只在等值成立的译版之间计算差距；其余明说不可比。"""
    connected = _version_scale_map(data, supported_pairs)
    main_version = {
        (d.round, d.preferred): d.default_version for d in data.rounds
    }
    by_language: dict[tuple[str, str], LanguageRollup] = {
        (r.preferred, r.concept): r for r in rollup_language(estimates)
    }
    gaps: list[dict] = []
    languages = sorted({d.preferred for d in data.rounds})
    round_ids = sorted({d.round for d in data.rounds})
    concepts = data.concepts
    for concept in concepts:
        comparable_versions = connected.get(concept, set())
        for i, la in enumerate(languages):
            for lb in languages[i + 1 :]:
                va = next(
                    (main_version[(rid, la)] for rid in round_ids if (rid, la) in main_version),
                    None,
                )
                vb = next(
                    (main_version[(rid, lb)] for rid in round_ids if (rid, lb) in main_version),
                    None,
                )
                ra = by_language.get((la, concept))
                rb = by_language.get((lb, concept))
                if ra is None or rb is None or va is None or vb is None:
                    continue
                if va in comparable_versions and vb in comparable_versions:
                    gaps.append(
                        {
                            "concept": concept,
                            "language_a": la,
                            "language_b": lb,
                            "gap": ra.point - rb.point,
                            "low": ra.low_bound - rb.high_bound,
                            "high": ra.high_bound - rb.low_bound,
                            "status": "可比较",
                            "note": "两译版锚题等值成立，差距按熟练读者桥接口径解释",
                        }
                    )
                else:
                    gaps.append(
                        {
                            "concept": concept,
                            "language_a": la,
                            "language_b": lb,
                            "gap": math.nan,
                            "low": math.nan,
                            "high": math.nan,
                            "status": "尺度未验证",
                            "note": (
                                f"{va} 与 {vb} 在 {concept} 上无成立桥接，"
                                "差距不得用于培训分配，仅提示待核实"
                            ),
                        }
                    )
    return gaps
