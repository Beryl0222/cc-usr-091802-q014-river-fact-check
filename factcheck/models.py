"""黄河叙事事实核验的领域模型。

仅使用标准库与纯 Python 数据结构，便于后续替换持久化方案。
注意：任何面向发布视图或读者视图的结构都不得包含讲述人联系方式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class MaterialType:
    """素材类型。"""

    ORAL = "oral"  # 口述
    IMAGE = "image"  # 影像
    ARCHIVE = "archive"  # 公开档案
    HYDROLOGY = "hydrology"  # 水文记录
    ALL = (ORAL, IMAGE, ARCHIVE, HYDROLOGY)


class ClaimStatus:
    """陈述的核验状态。只有编辑能把状态从待核验改为其余三种。"""

    PENDING = "pending"  # 待核验
    VERIFIED = "verified"  # 成立
    QUESTIONABLE = "questionable"  # 存疑
    RESTRICTED = "restricted"  # 不宜公开
    ALL = (PENDING, VERIFIED, QUESTIONABLE, RESTRICTED)
    DECIDABLE = (VERIFIED, QUESTIONABLE, RESTRICTED)


STATUS_LABELS = {
    ClaimStatus.PENDING: "待核验",
    ClaimStatus.VERIFIED: "成立",
    ClaimStatus.QUESTIONABLE: "存疑",
    ClaimStatus.RESTRICTED: "不宜公开",
}


class Relation:
    """引用关系。"""

    SUPPORTS = "supports"  # 支持
    CONTRADICTS = "contradicts"  # 冲突
    CONTEXT = "context"  # 背景
    ALL = (SUPPORTS, CONTRADICTS, CONTEXT)


class HintKind:
    """自动提示类型。提示仅供编辑参考，不构成核验决定。"""

    CONTRADICTION = "contradiction"  # 矛盾提示
    SIMILAR = "similar"  # 相似线索
    PLACE_UNRESOLVED = "place_unresolved"  # 旧地名未匹配现址
    EVIDENCE_REVISED = "evidence_revised"  # 引用证据被修订
    AUTO_KINDS = (CONTRADICTION, SIMILAR, PLACE_UNRESOLVED)


class CorrectionKind:
    CORRECTION = "correction"  # 更正
    RETRACTION = "retraction"  # 撤回


CORRECTION_LABELS = {
    CorrectionKind.CORRECTION: "更正",
    CorrectionKind.RETRACTION: "撤回",
}

EVENT_LABELS = {
    "flood": "洪水",
    "breach": "决口",
    "drought": "干旱",
    "relocation": "搬迁",
}

# 公开范围级别：讲述人分别限定姓名、精确位置、影像的公开范围
NAME_LEVELS = ("public", "pseudonym", "internal")  # 公开 / 化名 / 不公开
LOCATION_LEVELS = ("precise", "county", "internal")  # 精确 / 县级 / 不公开
IMAGE_LEVELS = ("public", "internal")  # 公开 / 不公开
SCOPE_LEVELS = {"name": NAME_LEVELS, "location": LOCATION_LEVELS, "image": IMAGE_LEVELS}
SCOPES = tuple(SCOPE_LEVELS)

SCOPE_LABELS = {"all": "全部", "name": "姓名", "location": "精确位置", "image": "影像"}


@dataclass
class Consent:
    """讲述人对姓名、精确位置、影像分别设定的公开范围。

    默认全部不公开（internal），由讲述人逐项授予；withdrawn 记录撤回的
    范围，"all" 表示整体撤回。撤回后对应范围一律按 internal 处理。
    """

    levels: dict = field(
        default_factory=lambda: {scope: levels[-1] for scope, levels in SCOPE_LEVELS.items()}
    )
    withdrawn: list = field(default_factory=list)

    def effective(self, scope: str) -> str:
        if "all" in self.withdrawn or scope in self.withdrawn:
            return "internal"
        return self.levels.get(scope, "internal")

    @property
    def fully_withdrawn(self) -> bool:
        return "all" in self.withdrawn


@dataclass
class Narrator:
    """讲述人。contact 仅供编辑部内部联系，任何发布视图与读者视图都不得包含。"""

    id: str
    name: str
    contact: str = ""
    consent: Consent = field(default_factory=Consent)


@dataclass
class Material:
    """素材：口述、影像、公开档案或水文记录。

    year_start/year_end 允许只填大致范围；fragments 保存图片片段或口述片段；
    records 保存结构化记录（如水文站逐年的洪峰事件、档案条目）。
    """

    id: str
    type: str
    title: str
    narrator_id: Optional[str] = None
    year_start: Optional[int] = None
    year_end: Optional[int] = None
    place: Optional[str] = None
    fragments: list = field(default_factory=list)
    records: list = field(default_factory=list)


@dataclass
class Citation:
    """陈述与证据之间的引用，由编辑逐一建立。"""

    id: str
    claim_id: str
    material_id: str
    relation: str
    note: str = ""
    fragment: Optional[str] = None
    created_by: str = ""


@dataclass
class Hint:
    """自动提示：矛盾或相似线索。generated_by 固定为 auto，不构成核验决定。"""

    id: str
    claim_id: str
    kind: str
    message: str
    refs: list = field(default_factory=list)
    generated_by: str = "auto"


@dataclass
class Decision:
    """编辑作出的核验决定，留痕可审计。"""

    editor_id: str
    status: str
    rationale: str
    at: str


@dataclass
class Claim:
    """口述中的具体陈述。"""

    id: str
    narrator_id: str
    material_id: str
    text: str
    year_start: int
    year_end: int
    place_name: str
    event: Optional[str] = None
    location_candidates: list = field(default_factory=list)
    status: str = ClaimStatus.PENDING
    citations: list = field(default_factory=list)
    hints: list = field(default_factory=list)
    decisions: list = field(default_factory=list)


@dataclass
class Version:
    """已刊发版本的脱敏快照。历史版本只读，修订只能以更正记录指出受影响陈述。"""

    number: int
    published_at: str
    published_by: str
    statements: list = field(default_factory=list)
    gaps: list = field(default_factory=list)


@dataclass
class Correction:
    """读者可见的更正或撤回记录，只指出受影响的陈述，不重写历史版本。"""

    id: str
    story_id: str
    version: int
    kind: str
    affected_claim_ids: list = field(default_factory=list)
    note: str = ""
    at: str = ""


@dataclass
class Story:
    """专题稿件。draft 阶段可增删陈述；published 后版本只增不改。"""

    id: str
    title: str
    claim_ids: list = field(default_factory=list)
    status: str = "draft"  # draft / published
    versions: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
