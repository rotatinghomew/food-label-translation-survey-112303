"""读入六张交接表、校验格式并套用更正（撤回/停用）。

设计要点
--------
1. 所有表按 UTF-8、带表头 CSV 读入，沿用交接脚本的 ``strict`` 宽度校验。
2. 更正表 ``corrections.csv`` 的 target 以 kind 决定含义：
   - 撤回答卷：target 是 response 标识。若 target 精确等于某行 response，只撤该行；
     若 target 是组前缀（如 r012b1 同时也是组 r012b 的首行命名），调用方可用
     ``include_group=True`` 撤掉同组（同 person、同桥接批次）的整组行。
     默认只撤被点名的行——撤回证据不能自动扩大到未点名的回答。
3. 译版停用只影响"停用日之后仍可安排的设计"，不删除历史回答；停用日前已完成的
   回答仍是该版的有效证据。
4. 桥接回答必须能回指到 invitations 中同一 person，且只能按该邀请的版本、
   bridge_p 与熟练资格解释（见 :class:`SurveyData` 的校验）。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

TABLES = (
    "items.csv",
    "rounds.csv",
    "invitations.csv",
    "responses.csv",
    "corrections.csv",
    "appointments.csv",
)

# 逐题编码约定（与 README 一致）
CODE_MISCONCEPTION = "0"   # 误解
CODE_CORRECT = "1"         # 正确
CODE_MISSING = ""          # 未观察

BRIDGE_ORIGINAL = "原版"
BRIDGE_BLIND = "盲复测"
BRIDGE_SHOWN = "访谈"      # 先展示答案后的访谈，不能用于独立尺度判断

CONSENT_REVISIT = "可补访"
CONSENT_ANALYSIS_ONLY = "只准分析"

SLOT_OPEN = "开放"
SLOT_BOOKED = "已预约"

WITHDRAW_KIND = "撤回答卷"
DEACTIVATE_KIND = "译版停用"


def _parse_day(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    return date.fromisoformat(text)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader)
        except StopIteration:
            raise ValueError(f"{path.name} 为空表")
        if not header or len(header) != len(set(header)):
            raise ValueError(f"{path.name} 的列名缺失或重复")
        rows: list[dict[str, str]] = []
        for line, record in enumerate(reader, start=2):
            if len(record) != len(header):
                raise ValueError(f"{path.name} 第 {line} 行宽度与表头不一致")
            rows.append({key: value.strip() for key, value in zip(header, record)})
    return rows


@dataclass(frozen=True)
class Item:
    version: str
    item: str
    position: int
    concept: str
    anchor: str  # 空串表示非锚题


@dataclass(frozen=True)
class Invitation:
    person: str
    round: str
    preferred: str
    channel: str
    fluent: bool
    selection_p: float
    invited_at: date | None
    consent: str
    assigned_version: str
    bridge_p: float | None
    bridge_eligible: bool

    @property
    def contacted(self) -> bool:
        return self.invited_at is not None


@dataclass(frozen=True)
class ResponseRow:
    response: str
    person: str
    version: str
    item: str
    position: int
    bridge: str
    code: str  # "0" / "1" / ""
    answered_at: date
    withdrawn: bool = False


@dataclass(frozen=True)
class Correction:
    change: str
    day: date
    kind: str
    target: str


@dataclass(frozen=True)
class Appointment:
    slot: str
    day: date
    interviewer: str
    from_version: str
    to_version: str
    person: str  # 空串表示开放席位
    kind: str
    status: str
    rebook_after: date | None


@dataclass(frozen=True)
class RoundDesign:
    round: str
    preferred: str
    default_version: str
    bridge_1: str
    bridge_2: str
    eligible: str  # 全体 / 熟练
    cutoff: date


@dataclass
class SurveyData:
    """读入并校验后的一轮资料；更正已按规则套用。"""

    items: list[Item]
    rounds: list[RoundDesign]
    invitations: dict[str, Invitation]
    responses: list[ResponseRow]
    corrections: list[Correction]
    appointments: list[Appointment]
    withdrawn_response_ids: set[str] = field(default_factory=set)
    deactivated_versions: dict[str, date] = field(default_factory=dict)
    validation_notes: list[str] = field(default_factory=list)

    # ---- 便捷索引 ----
    @property
    def item_index(self) -> dict[tuple[str, str], Item]:
        return {(it.version, it.item): it for it in self.items}

    @property
    def anchors(self) -> dict[str, dict[str, Item]]:
        """anchor 标识 -> 版本 -> 题项。"""
        out: dict[str, dict[str, Item]] = {}
        for it in self.items:
            if it.anchor:
                out.setdefault(it.anchor, {})[it.version] = it
        return out

    @property
    def concepts(self) -> list[str]:
        seen: list[str] = []
        for it in self.items:
            if it.concept not in seen:
                seen.append(it.concept)
        return seen

    def version_items(self, version: str) -> list[Item]:
        return [it for it in self.items if it.version == version]

    def active_responses(self, include_withdrawn: bool = False) -> list[ResponseRow]:
        if include_withdrawn:
            return list(self.responses)
        return [r for r in self.responses if not r.withdrawn]

    def round_design(self, round_id: str, preferred: str) -> RoundDesign:
        for design in self.rounds:
            if design.round == round_id and design.preferred == preferred:
                return design
        raise KeyError(f"缺少 {round_id}/{preferred} 的轮次设计")


def load_survey(directory: str | Path, *, withdraw_groups: bool = False) -> SurveyData:
    directory = Path(directory)
    missing = [name for name in TABLES if not (directory / name).exists()]
    if missing:
        raise FileNotFoundError(f"资料目录缺少：{', '.join(missing)}")

    raw = {name: read_csv(directory / name) for name in TABLES}

    items = [
        Item(
            version=r["version"],
            item=r["item"],
            position=int(r["position"]),
            concept=r["concept"],
            anchor=r["anchor"],
        )
        for r in raw["items.csv"]
    ]
    rounds = [
        RoundDesign(
            round=r["round"],
            preferred=r["preferred"],
            default_version=r["default_version"],
            bridge_1=r["bridge_1"],
            bridge_2=r["bridge_2"],
            eligible=r["eligible"],
            cutoff=date.fromisoformat(r["cutoff"]),
        )
        for r in raw["rounds.csv"]
    ]
    invitations = {}
    for r in raw["invitations.csv"]:
        if r["person"] in invitations:
            raise ValueError(f"invitations 中 person {r['person']} 重复")
        invitations[r["person"]] = Invitation(
            person=r["person"],
            round=r["round"],
            preferred=r["preferred"],
            channel=r["channel"],
            fluent=r["fluent"] == "1",
            selection_p=float(r["selection_p"]),
            invited_at=_parse_day(r["invited_at"]),
            consent=r["consent"],
            assigned_version=r["assigned_version"],
            bridge_p=float(r["bridge_p"]) if r["bridge_p"] else None,
            bridge_eligible=r["bridge_eligible"] == "1",
        )
    corrections = [
        Correction(
            change=r["change"],
            day=date.fromisoformat(r["day"]),
            kind=r["kind"],
            target=r["target"],
        )
        for r in raw["corrections.csv"]
    ]
    appointments = [
        Appointment(
            slot=r["slot"],
            day=date.fromisoformat(r["day"]),
            interviewer=r["interviewer"],
            from_version=r["from_version"],
            to_version=r["to_version"],
            person=r["person"],
            kind=r["kind"],
            status=r["status"],
            rebook_after=_parse_day(r["rebook_after"]),
        )
        for r in raw["appointments.csv"]
    ]

    responses = [
        ResponseRow(
            response=r["response"],
            person=r["person"],
            version=r["version"],
            item=r["item"],
            position=int(r["position"]),
            bridge=r["bridge"],
            code=r["code"],
            answered_at=date.fromisoformat(r["answered_at"]),
        )
        for r in raw["responses.csv"]
    ]

    data = SurveyData(
        items=items,
        rounds=rounds,
        invitations=invitations,
        responses=responses,
        corrections=corrections,
        appointments=appointments,
    )
    _validate_structure(data)
    _apply_corrections(data, withdraw_groups=withdraw_groups)
    return data


def _validate_structure(data: SurveyData) -> None:
    """结构性校验：回答必须回指邀请与题项，桥接资格与设计必须对得上。"""
    notes: list[str] = []
    item_index = data.item_index

    # 1. 题项表：同版内题序/题号唯一，锚题跨版概念一致
    seen: set[tuple[str, str]] = set()
    seen_pos: set[tuple[str, int]] = set()
    for it in data.items:
        if (it.version, it.item) in seen:
            raise ValueError(f"items 中 {it.version}/{it.item} 重复")
        seen.add((it.version, it.item))
        if (it.version, it.position) in seen_pos:
            raise ValueError(f"items 中 {it.version} 题序 {it.position} 重复")
        seen_pos.add((it.version, it.position))
    anchor_concept: dict[str, str] = {}
    for anchor, per_version in data.anchors.items():
        concepts = {it.concept for it in per_version.values()}
        if len(concepts) != 1:
            raise ValueError(f"锚题 {anchor} 跨版概念不一致：{concepts}")
        anchor_concept[anchor] = concepts.pop()

    # 2. 回答回指邀请与题项；位置与 items 一致；编码合法
    response_ids: set[str] = set()
    for r in data.responses:
        if r.response in response_ids:
            raise ValueError(f"responses 中 response {r.response} 重复")
        response_ids.add(r.response)
        if r.person not in data.invitations:
            raise ValueError(f"回答 {r.response} 的 person {r.person} 不在邀请框内")
        if (r.version, r.item) not in item_index:
            raise ValueError(f"回答 {r.response} 指向未知题项 {r.version}/{r.item}")
        if item_index[(r.version, r.item)].position != r.position:
            raise ValueError(f"回答 {r.response} 的题序与 items.csv 不一致")
        if r.code not in (CODE_MISCONCEPTION, CODE_CORRECT, CODE_MISSING):
            raise ValueError(f"回答 {r.response} 编码非法：{r.code!r}")

    # 3. 原版必须落在本人被指派的版本；桥接必须有熟练资格与 bridge_p
    for r in data.responses:
        invitation = data.invitations[r.person]
        if r.bridge == BRIDGE_ORIGINAL and r.version != invitation.assigned_version:
            raise ValueError(
                f"回答 {r.response} 的原版版本 {r.version} 与邀请指派 "
                f"{invitation.assigned_version} 不符"
            )
        if r.bridge in (BRIDGE_BLIND, BRIDGE_SHOWN):
            if not invitation.bridge_eligible or invitation.bridge_p is None:
                raise ValueError(
                    f"回答 {r.response} 是桥接，但 {r.person} 的邀请没有桥接资格/概率"
                )
            if not invitation.fluent:
                notes.append(
                    f"回答 {r.response} 为桥接但受访者未标熟练（{r.person}），"
                    "桥接结论只能限定在实际覆盖人群"
                )

    # 3b. 邀请框内桥接资格与 bridge_p 必须自洽
    for invitation in data.invitations.values():
        if invitation.bridge_eligible and invitation.bridge_p is None:
            raise ValueError(
                f"邀请 {invitation.person} 标记桥接合格却没有 bridge_p"
            )
        if not invitation.bridge_eligible and invitation.bridge_p is not None:
            raise ValueError(
                f"邀请 {invitation.person} 无桥接资格却带 bridge_p，设计自相矛盾"
            )

    # 4. 轮次设计的语言与邀请框对得上
    preferred_rounds = {(d.round, d.preferred) for d in data.rounds}
    for invitation in data.invitations.values():
        key = (invitation.round, invitation.preferred)
        if key not in preferred_rounds:
            raise ValueError(f"邀请 {invitation.person} 的轮次/语言缺少 rounds 设计")
        design = data.round_design(invitation.round, invitation.preferred)
        if invitation.assigned_version != design.default_version:
            notes.append(
                f"邀请 {invitation.person} 指派版本 {invitation.assigned_version} "
                f"与 {invitation.preferred} 主版 {design.default_version} 不同"
            )

    # 5. 预约：slot 唯一；已预约必须有人，开放必须无人
    slots: set[str] = set()
    for appt in data.appointments:
        if appt.slot in slots:
            raise ValueError(f"appointments 中 slot {appt.slot} 重复")
        slots.add(appt.slot)
        if appt.status == SLOT_BOOKED and not appt.person:
            raise ValueError(f"slot {appt.slot} 已预约却没有 person")
        if appt.status == SLOT_OPEN and appt.person:
            raise ValueError(f"slot {appt.slot} 标记开放却占用了 person {appt.person}")

    data.validation_notes = notes


def _apply_corrections(data: SurveyData, *, withdraw_groups: bool) -> None:
    withdrawn: set[str] = set()
    for correction in data.corrections:
        if correction.kind == WITHDRAW_KIND:
            target = correction.target
            exact = [r for r in data.responses if r.response == target]
            if not exact:
                # 允许 target 是组前缀（如 r012b 指代 r012b1..r012b3）
                prefix_matches = [r for r in data.responses if r.response.startswith(target)]
                if not prefix_matches:
                    raise ValueError(f"撤回更正 {correction.change} 找不到目标 {target}")
                withdrawn.update(r.response for r in prefix_matches)
                continue
            withdrawn.add(target)
            if withdraw_groups:
                row = exact[0]
                siblings = [
                    r
                    for r in data.responses
                    if r.person == row.person
                    and r.bridge == row.bridge
                    and r.response != target
                ]
                withdrawn.update(r.response for r in siblings)
        elif correction.kind == DEACTIVATE_KIND:
            if correction.target not in {it.version for it in data.items}:
                raise ValueError(
                    f"停用更正 {correction.change} 指向未知译版 {correction.target}"
                )
            data.deactivated_versions[correction.target] = correction.day
        else:
            raise ValueError(f"未知更正类型：{correction.kind}")

    data.withdrawn_response_ids = withdrawn
    for row in data.responses:
        if row.response in withdrawn:
            object.__setattr__(row, "withdrawn", True)
