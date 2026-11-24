"""共同题等值核对：哪些锚题仍能支撑跨语言比较。

判定原则（与调查口径一致）：

* 只有同一人、同一锚题在两个译版上都观察到的"盲复测"配对才能用于等值判断；
  "访谈"组在答题前已看到答案，不是独立测量，一律不进入等值计算。
* 已撤回的回答不进入任何配对。
* 桥接样本全部来自熟练读者时，结论的适用人群只能写"熟练读者"，不能外推全体。
* 顺序、语言版、受访人差异只有在设计上能分开时才分开；同一桥接里两版锚题
  位置若都不同，顺序效应与译版效应不可分离，必须明说并降级。
* 非锚题没有跨版本对应物，不产生任何跨语言结论，禁止用来"补"跨组差距。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import binomtest, fisher_exact

from .io import BRIDGE_BLIND, BRIDGE_ORIGINAL, SurveyData

# 等值判定阈值（写在一处，便于评审与复核）
AGREE_SUPPORT = 0.80      # Wilson 下限 >= 0.80 视为等值成立
AGREE_FAIL = 0.70         # 点估计 < 0.70 视为等值失败
MIN_PAIRS = 5             # 配对数不足时只能给"证据不足"
# 小样本下全一致时 Wilson 下限天然偏低，单独给一条全一致通道，
# 但仍要求达到 MIN_PAIRS，避免 2/2 这种极薄证据被当成成立。
PERFECT_AGREE_MIN = 5


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson 95% 区间；n=0 时返回 (nan, nan)。"""
    if n == 0:
        return math.nan, math.nan
    p = successes / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (center - half) / denom, (center + half) / denom


@dataclass
class AnchorPair:
    """同一受访者在某锚题上的两版观察。"""

    person: str
    anchor: str
    concept: str
    version_a: str
    version_b: str
    code_a: int
    code_b: int

    @property
    def agree(self) -> bool:
        return self.code_a == self.code_b

    @property
    def flipped_correct_to_wrong(self) -> bool:
        return self.code_a == 1 and self.code_b == 0

    @property
    def flipped_wrong_to_correct(self) -> bool:
        return self.code_a == 0 and self.code_b == 1


@dataclass
class BridgeEquivalence:
    """一个版本对（version_a -> version_b）在单个锚题上的等值结果。"""

    version_a: str
    version_b: str
    anchor: str
    concept: str
    n_pairs: int
    n_agree: int
    n_disagree: int
    n_correct_to_wrong: int
    n_wrong_to_correct: int
    n_missing_partner: int
    positions: tuple[int, int]
    order_confounded: bool
    agree_rate: float
    wilson_low: float
    wilson_high: float
    binom_p_vs_half: float
    status: str          # 成立 / 失败 / 证据不足
    applies_to: str      # 适用人群说明
    note: str


@dataclass
class BridgeReport:
    version_a: str
    version_b: str
    eligible_population: str          # 全体 / 熟练
    n_persons: int
    person_fluent_only: bool
    observed_orientations: tuple[str, ...]  # 实际观察到的桥接方向
    anchor_reports: list[BridgeEquivalence]
    discordance_fisher_p: float       # 与最强桥接对比的费雪检验 p（见报告注记）
    separable_order: bool
    note: str


@dataclass
class NonAnchorCoverage:
    version: str
    item: str
    concept: str
    position: int
    anchor_versions: tuple[str, ...]  # 同概念锚题覆盖的译版
    cross_language_supported: bool
    note: str


def _observed(data: SurveyData) -> dict[str, dict[tuple[str, str, str], int]]:
    """person -> (bridge, version, item) -> 0/1；撤回与缺失不收录。"""
    out: dict[str, dict[tuple[str, str, str], int]] = {}
    for row in data.active_responses():
        if row.code == "":
            continue
        out.setdefault(row.person, {})[(row.bridge, row.version, row.item)] = int(row.code)
    return out


def _bridge_versions_for_person(data: SurveyData, person: str) -> set[str]:
    return {
        row.version
        for row in data.active_responses()
        if row.person == person and row.bridge == BRIDGE_BLIND
    }


def build_pairs(
    data: SurveyData, version_a: str, version_b: str, anchor: str
) -> tuple[list[AnchorPair], int]:
    """构造某锚题的盲复测配对，并统计因撤回/缺失而无法配对的人次。

     rounds.csv 里的桥接是有方向的（bridge_1 原版 -> bridge_2 盲测），
    但实际数据可能只落在任一方向上。这里按"谁有盲测观察"自动定向：
    - 受访者在 version_b 有盲测：(version_a 原版, version_b 盲测)
    - 受访者在 version_a 有盲测：(version_b 原版, version_a 盲测)
    返回的 AnchorPair 仍以入参 (version_a, version_b) 的方向记 code_a/code_b，
    反向观察会交换编码，保证"正确->误解"的方向解读与版本对方向一致。
    """
    observed = _observed(data)
    item_a = data.anchors[anchor][version_a]
    item_b = data.anchors[anchor][version_b]
    persons = sorted(
        {
            row.person
            for row in data.active_responses()
            if row.bridge == BRIDGE_BLIND and row.version in (version_a, version_b)
        }
    )
    pairs: list[AnchorPair] = []
    missing_partner = 0
    for person in persons:
        blind_versions = _bridge_versions_for_person(data, person) & {version_a, version_b}
        person_matched = False
        person_missing = 0
        if version_b in blind_versions:
            key_a = (BRIDGE_ORIGINAL, version_a, item_a.item)
            key_b = (BRIDGE_BLIND, version_b, item_b.item)
            if key_a in observed[person] and key_b in observed[person]:
                pairs.append(
                    AnchorPair(
                        person=person,
                        anchor=anchor,
                        concept=item_a.concept,
                        version_a=version_a,
                        version_b=version_b,
                        code_a=observed[person][key_a],
                        code_b=observed[person][key_b],
                    )
                )
                person_matched = True
            else:
                person_missing += 1
        if version_a in blind_versions:
            # 反向桥接：盲测在 version_a，原版在 version_b
            key_a = (BRIDGE_BLIND, version_a, item_a.item)
            key_b = (BRIDGE_ORIGINAL, version_b, item_b.item)
            if key_a in observed[person] and key_b in observed[person]:
                pairs.append(
                    AnchorPair(
                        person=person,
                        anchor=anchor,
                        concept=item_a.concept,
                        version_a=version_a,
                        version_b=version_b,
                        # 交换方向，使 code_a 对应 version_a、code_b 对应 version_b
                        code_a=observed[person][key_a],
                        code_b=observed[person][key_b],
                    )
                )
                person_matched = True
            else:
                person_missing += 1
        # 该人在这个锚题上没有任何完整配对时，只计一次未配对
        if not person_matched:
            missing_partner += max(1, person_missing)
    return pairs, missing_partner


def _classify(n_pairs: int, n_agree: int, wilson_low: float) -> str:
    if n_pairs < MIN_PAIRS:
        return "证据不足"
    rate = n_agree / n_pairs
    if wilson_low >= AGREE_SUPPORT:
        return "成立"
    if n_agree == n_pairs and n_pairs >= PERFECT_AGREE_MIN:
        # 全一致但样本薄：成立，同时在备注里保留 Wilson 下限供评审
        return "成立"
    if rate < AGREE_FAIL:
        return "失败"
    return "证据不足"


def anchor_equivalence(
    data: SurveyData, version_a: str, version_b: str, anchor: str
) -> BridgeEquivalence:
    pairs, missing_partner = build_pairs(data, version_a, version_b, anchor)
    n = len(pairs)
    n_agree = sum(p.agree for p in pairs)
    n_disagree = n - n_agree
    n_10 = sum(p.flipped_correct_to_wrong for p in pairs)
    n_01 = sum(p.flipped_wrong_to_correct for p in pairs)
    low, high = wilson_interval(n_agree, n)
    p_value = binomtest(n_agree, n, 0.5).pvalue if n else math.nan
    item_a = data.anchors[anchor][version_a]
    item_b = data.anchors[anchor][version_b]
    confounded = item_a.position != item_b.position
    status = _classify(n, n_agree, low)

    fluent_only = _bridge_fluent_only(data, version_a, version_b)
    applies_to = "熟练读者（桥接仅覆盖熟练受访者）" if fluent_only else "全体合格受访者"
    notes: list[str] = []
    if confounded:
        notes.append(
            f"两版锚题位置不同（{version_a} 第 {item_a.position} 题 vs "
            f"{version_b} 第 {item_b.position} 题），顺序效应与译版效应不可分离"
        )
    if n_10 > n_01:
        notes.append(
            f"分歧以 {version_a} 正确而 {version_b} 判误解为主（{n_10}:{n_01}），"
            f"提示 {version_b} 译法可能压低正确判断"
        )
    elif n_01 > n_10:
        notes.append(f"反向分歧较多（误解→正确 {n_01}:{n_10}）")
    if missing_partner:
        notes.append(f"{missing_partner} 人次因撤回或缺失无法配对")
    if n < MIN_PAIRS:
        notes.append(f"配对数 {n} 低于最小要求 {MIN_PAIRS}，不下等值结论")
    elif status == "成立" and low < AGREE_SUPPORT and n_agree == n:
        notes.append(
            f"全一致但样本仅 {n} 对，按全一致通道判成立；"
            f"Wilson 下限 {low:.3f} 偏低，补访应优先加厚该桥接"
        )

    return BridgeEquivalence(
        version_a=version_a,
        version_b=version_b,
        anchor=anchor,
        concept=item_a.concept,
        n_pairs=n,
        n_agree=n_agree,
        n_disagree=n_disagree,
        n_correct_to_wrong=n_10,
        n_wrong_to_correct=n_01,
        n_missing_partner=missing_partner,
        positions=(item_a.position, item_b.position),
        order_confounded=confounded,
        agree_rate=(n_agree / n if n else math.nan),
        wilson_low=low,
        wilson_high=high,
        binom_p_vs_half=p_value,
        status=status,
        applies_to=applies_to,
        note="；".join(notes),
    )


def _bridge_persons(data: SurveyData, version_a: str, version_b: str) -> list[str]:
    """在版本对任一版上留下盲复测观察的受访者。"""
    persons = {
        row.person
        for row in data.active_responses()
        if row.bridge == BRIDGE_BLIND and row.version in (version_a, version_b)
    }
    return sorted(persons)


def _bridge_fluent_only(data: SurveyData, version_a: str, version_b: str) -> bool:
    persons = _bridge_persons(data, version_a, version_b)
    if not persons:
        return True
    return all(data.invitations[p].fluent for p in persons)


def bridge_report(
    data: SurveyData,
    version_a: str,
    version_b: str,
    eligible_population: str,
    reference: tuple[str, str] | None = None,
) -> BridgeReport:
    """汇总一个版本对上全部锚题的等值结果。

    reference 是另一个已判为等值的版本对，用于做分歧率费雪对比；没有则给 nan。
    """
    anchor_reports = [
        anchor_equivalence(data, version_a, version_b, anchor)
        for anchor in sorted(data.anchors)
        if version_a in data.anchors[anchor] and version_b in data.anchors[anchor]
    ]
    persons = _bridge_persons(data, version_a, version_b)
    fluent_only = _bridge_fluent_only(data, version_a, version_b)
    orientations = tuple(
        sorted(
            {
                (
                    f"{version_a}原版->{version_b}盲测"
                    if version_b in _bridge_versions_for_person(data, p)
                    else f"{version_b}原版->{version_a}盲测"
                )
                for p in persons
            }
        )
    )

    # 可分性：只要该版本对存在任一锚题位置相同，顺序效应就有被分离的机会；
    # 全部锚题位置都互换，则顺序与译版完全混杂。
    separable = any(not rep.order_confounded for rep in anchor_reports)

    fisher_p = math.nan
    if reference is not None:
        ref_dis, ref_n = _pooled_discordance(data, *reference)
        cur_dis = sum(rep.n_disagree for rep in anchor_reports)
        cur_n = sum(rep.n_pairs for rep in anchor_reports)
        if cur_n and ref_n:
            fisher_p = fisher_exact(
                [[cur_dis, cur_n - cur_dis], [ref_dis, ref_n - ref_dis]],
                alternative="two-sided",
            ).pvalue

    notes: list[str] = []
    if eligible_population == "熟练" or fluent_only:
        notes.append("桥接只覆盖熟练读者，结论不得外推非熟练人群")
    if not separable:
        notes.append("该版本对所有共同题位置都不同，顺序与译版效应无法分开")
    if len(orientations) > 1:
        notes.append(f"实际数据同时含两个方向的桥接：{'、'.join(orientations)}")
    if fisher_p is not math.nan and fisher_p < 0.05:
        notes.append(
            f"分歧率显著高于参考桥接 {reference[0]}->{reference[1]}（Fisher p={fisher_p:.3f}）"
        )

    return BridgeReport(
        version_a=version_a,
        version_b=version_b,
        eligible_population=eligible_population,
        n_persons=len(persons),
        person_fluent_only=fluent_only,
        observed_orientations=orientations,
        anchor_reports=anchor_reports,
        discordance_fisher_p=fisher_p,
        separable_order=separable,
        note="；".join(notes),
    )


def _pooled_discordance(data: SurveyData, version_a: str, version_b: str) -> tuple[int, int]:
    total_dis = total_n = 0
    for anchor in data.anchors:
        if version_a in data.anchors[anchor] and version_b in data.anchors[anchor]:
            pairs, _ = build_pairs(data, version_a, version_b, anchor)
            total_n += len(pairs)
            total_dis += sum(not p.agree for p in pairs)
    return total_dis, total_n


def non_anchor_coverage(data: SurveyData) -> list[NonAnchorCoverage]:
    """列出非锚题，并明确其跨语言比较状态（一律不支持）。"""
    anchor_versions_by_concept: dict[str, set[str]] = {}
    for per_version in data.anchors.values():
        for version, item in per_version.items():
            anchor_versions_by_concept.setdefault(item.concept, set()).add(version)
    out: list[NonAnchorCoverage] = []
    for item in sorted(data.items, key=lambda it: (it.version, it.position)):
        if item.anchor:
            continue
        covered = tuple(sorted(anchor_versions_by_concept.get(item.concept, set())))
        out.append(
            NonAnchorCoverage(
                version=item.version,
                item=item.item,
                concept=item.concept,
                position=item.position,
                anchor_versions=covered,
                cross_language_supported=False,
                note=(
                    f"{item.item} 只存在于 {item.version}，无跨版对应题；"
                    "只能做该译版内的单独估计，禁止据此补跨语言差距"
                ),
            )
        )
    return out


def scale_check(data: SurveyData) -> list[BridgeReport]:
    """按 rounds.csv 的桥接设计逐对核对，版本对按无向去重。

    rounds.csv 里每个语言写一条有向设计（bridge_1 -> bridge_2），同一对译版
    可能被多个语言以相反方向引用。等值判断本身是无向的，因此这里：
    - 版本对按无向归并，报告方向取 rounds 中首次出现的方向；
    - 合格口径取并集中更宽的一个（"全体" 宽于 "熟练"）；
    - 实际观察方向（谁做盲测）在 BridgeReport.observed_orientations 里明说。
    """
    pair_meta: dict[frozenset[str], dict] = {}
    for design in data.rounds:
        key = frozenset((design.bridge_1, design.bridge_2))
        meta = pair_meta.setdefault(
            key,
            {
                "direction": (design.bridge_1, design.bridge_2),
                "eligible": design.eligible,
            },
        )
        if design.eligible == "全体":
            meta["eligible"] = "全体"
    pre: list[tuple[frozenset[str], int, int]] = []
    for key, meta in pair_meta.items():
        dis, n = _pooled_discordance(data, *meta["direction"])
        pre.append((key, dis, n))
    reference_key = min(
        pre, key=lambda x: (x[1] / x[2] if x[2] else 1.0, -x[2])
    )[0]
    reports: list[BridgeReport] = []
    for key, meta in sorted(pair_meta.items(), key=lambda kv: kv[1]["direction"]):
        va, vb = meta["direction"]
        reference = (
            tuple(pair_meta[reference_key]["direction"])
            if key != reference_key
            else None
        )
        reports.append(
            bridge_report(data, va, vb, meta["eligible"], reference=reference)
        )
    return reports
