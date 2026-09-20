"""事实核验核心服务。

职责边界：
- 编辑在此把口述陈述与图片片段、地点候选、时间范围、公开档案、水文记录
  逐一建立引用；
- 自动能力（factcheck.hints）只提示矛盾与相似线索，不改变任何核验状态；
- 成立 / 存疑 / 不宜公开的决定只能由 editor 角色的编辑作出；
- 讲述人授权、撤回、稿件发布快照、更正与撤回记录均在此维护；
- 已刊发版本只读：修订与撤回只生成指向受影响陈述的更正记录。
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

from . import hints as auto_hints
from .models import (
    CORRECTION_LABELS,
    EVENT_LABELS,
    SCOPE_LABELS,
    SCOPE_LEVELS,
    STATUS_LABELS,
    Claim,
    ClaimStatus,
    Consent,
    Correction,
    CorrectionKind,
    Citation,
    Decision,
    Hint,
    HintKind,
    Material,
    MaterialType,
    Narrator,
    Relation,
    Story,
    Version,
)

EDITOR_ROLE = "editor"


class ValidationError(Exception):
    """输入或流程不合法。"""


class NotFoundError(Exception):
    """对象不存在。"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pseudonym(name):
    name = (name or "").strip()
    return f"{name[0]}某" if name else "匿名"


class FactCheckService:
    """黄河叙事事实核验的核心服务。"""

    def __init__(self, gazetteer=None):
        self.gazetteer = list(gazetteer or [])
        self.narrators = {}
        self.materials = {}
        self.claims = {}
        self.stories = {}
        self._seq = {}

    # ---- 基础工具 ----

    def _next_id(self, prefix):
        self._seq[prefix] = self._seq.get(prefix, 0) + 1
        return f"{prefix}-{self._seq[prefix]:04d}"

    @staticmethod
    def _require_editor(actor):
        if not actor or actor.get("role") != EDITOR_ROLE:
            raise PermissionError("只有具备编辑权限的成员才能执行该操作")

    def _narrator(self, narrator_id):
        try:
            return self.narrators[narrator_id]
        except KeyError:
            raise NotFoundError(f"讲述人不存在：{narrator_id}") from None

    def _material(self, material_id):
        try:
            return self.materials[material_id]
        except KeyError:
            raise NotFoundError(f"素材不存在：{material_id}") from None

    def _claim(self, claim_id):
        try:
            return self.claims[claim_id]
        except KeyError:
            raise NotFoundError(f"陈述不存在：{claim_id}") from None

    def _story(self, story_id):
        try:
            return self.stories[story_id]
        except KeyError:
            raise NotFoundError(f"稿件不存在：{story_id}") from None

    # ---- 讲述人与授权 ----

    def register_narrator(self, name, contact="", consent_levels=None):
        if not name or not name.strip():
            raise ValidationError("讲述人姓名不能为空")
        narrator = Narrator(
            id=self._next_id("nar"), name=name.strip(), contact=contact, consent=Consent()
        )
        self.narrators[narrator.id] = narrator
        for scope, level in (consent_levels or {}).items():
            self.update_consent(narrator.id, scope, level)
        return narrator

    def update_consent(self, narrator_id, scope, level):
        """讲述人分别限定姓名、精确位置、影像的公开范围。"""
        narrator = self._narrator(narrator_id)
        if scope not in SCOPE_LEVELS:
            raise ValidationError(f"未知的公开范围：{scope}")
        if level not in SCOPE_LEVELS[scope]:
            raise ValidationError(f"范围 {scope} 不支持级别 {level}")
        narrator.consent.levels[scope] = level
        return narrator.consent

    def withdraw(self, narrator_id, scope="all", note=""):
        """撤回授权。

        未发布稿件立即停用相关素材（publishable 列入缺口、publish 拒绝）；
        已刊发内容保留当时版本，并生成读者可见的撤回记录。
        """
        narrator = self._narrator(narrator_id)
        if scope != "all" and scope not in SCOPE_LEVELS:
            raise ValidationError(f"未知的公开范围：{scope}")
        if scope not in narrator.consent.withdrawn:
            narrator.consent.withdrawn.append(scope)
        corrections = []
        for story in self.stories.values():
            if story.status != "published" or not story.versions:
                continue
            affected = [
                cid for cid in story.claim_ids if self.claims[cid].narrator_id == narrator_id
            ]
            if not affected:
                continue
            if not self._scope_exposed(story.versions[-1], affected, scope):
                continue
            corrections.append(
                self._add_correction(
                    story,
                    CorrectionKind.RETRACTION,
                    affected,
                    note
                    or f"讲述人撤回{SCOPE_LABELS[scope]}授权；已刊发版本保留当时依据，特此标注。",
                )
            )
        return corrections

    @staticmethod
    def _scope_exposed(version, claim_ids, scope):
        """已刊发快照中是否实际公开了被撤回的范围。"""
        if scope == "all":
            return True
        key = {"name": "narrator", "location": "location", "image": "images"}[scope]
        return any(
            st["claim_id"] in claim_ids and st.get(key) for st in version.statements
        )

    # ---- 素材与陈述 ----

    def register_material(
        self,
        material_type,
        title,
        narrator_id=None,
        year_start=None,
        year_end=None,
        place=None,
        fragments=None,
        records=None,
    ):
        if material_type not in MaterialType.ALL:
            raise ValidationError(f"未知的素材类型：{material_type}")
        if narrator_id is not None:
            self._narrator(narrator_id)
        if year_start is not None and year_end is not None and year_end < year_start:
            raise ValidationError("素材时间范围结束年份不能早于开始年份")
        material = Material(
            id=self._next_id("mat"),
            type=material_type,
            title=title,
            narrator_id=narrator_id,
            year_start=year_start,
            year_end=year_end,
            place=place,
            fragments=list(fragments or []),
            records=list(records or []),
        )
        self.materials[material.id] = material
        self._refresh_all_hints()
        return material

    def register_claim(
        self, narrator_id, material_id, text, year_start, year_end, place_name, event=None
    ):
        narrator = self._narrator(narrator_id)
        material = self._material(material_id)
        if material.narrator_id and material.narrator_id != narrator.id:
            raise ValidationError("陈述的讲述人与口述素材记录不一致")
        if not text or not text.strip():
            raise ValidationError("陈述内容不能为空")
        if year_end < year_start:
            raise ValidationError("时间范围结束年份不能早于开始年份")
        if event is not None and event not in EVENT_LABELS:
            raise ValidationError(f"未知的事件类型：{event}")
        claim = Claim(
            id=self._next_id("claim"),
            narrator_id=narrator.id,
            material_id=material.id,
            text=text.strip(),
            year_start=year_start,
            year_end=year_end,
            place_name=(place_name or "").strip(),
            event=event,
        )
        claim.location_candidates = auto_hints.location_candidates(
            claim.place_name, self.gazetteer
        )
        self.claims[claim.id] = claim
        self._refresh_all_hints()
        return claim

    # ---- 引用与自动提示 ----

    def add_citation(self, claim_id, material_id, relation, note="", fragment=None, actor=None):
        """编辑为陈述逐一建立对素材（可精确到片段）的引用。"""
        claim = self._claim(claim_id)
        material = self._material(material_id)
        if relation not in Relation.ALL:
            raise ValidationError(f"未知的引用关系：{relation}")
        if fragment and material.fragments:
            known = {f.get("id") for f in material.fragments}
            if fragment not in known:
                raise ValidationError(f"素材《{material.title}》中不存在片段 {fragment}")
        citation = Citation(
            id=self._next_id("cit"),
            claim_id=claim.id,
            material_id=material.id,
            relation=relation,
            note=note,
            fragment=fragment,
            created_by=(actor or {}).get("id", ""),
        )
        claim.citations.append(citation)
        return citation

    def refresh_hints(self, claim_id):
        """重新生成自动提示；保留证据修订等人工相关记录。"""
        claim = self._claim(claim_id)
        kept = [h for h in claim.hints if h.kind not in HintKind.AUTO_KINDS]
        generated = auto_hints.collect(claim, self.claims.values(), self.materials.values())
        for hint in generated:
            hint.id = self._next_id("hint")
        claim.hints = kept + generated
        return claim.hints

    def _refresh_all_hints(self):
        for claim_id in list(self.claims):
            self.refresh_hints(claim_id)

    # ---- 核验决定（仅编辑） ----

    def decide(self, claim_id, actor, status, rationale=""):
        """编辑作出成立 / 存疑 / 不宜公开的决定并留痕。"""
        self._require_editor(actor)
        if status not in ClaimStatus.DECIDABLE:
            raise ValidationError("核验决定只能是 成立 / 存疑 / 不宜公开")
        claim = self._claim(claim_id)
        claim.status = status
        decision = Decision(
            editor_id=actor.get("id", ""), status=status, rationale=rationale, at=_now()
        )
        claim.decisions.append(decision)
        return decision

    # ---- 证据修订 ----

    def revise_evidence(self, material_id, note, actor):
        """修订被引用的证据。

        同一证据被多个专题采用时，只为各专题生成指向受影响陈述的更正记录，
        不重写历史版本；相关陈述退回待核验，由编辑重新决定。
        """
        self._require_editor(actor)
        material = self._material(material_id)
        affected = [
            claim
            for claim in self.claims.values()
            if any(c.material_id == material_id for c in claim.citations)
        ]
        for claim in affected:
            claim.hints.append(
                Hint(
                    id=self._next_id("hint"),
                    claim_id=claim.id,
                    kind=HintKind.EVIDENCE_REVISED,
                    message=f"引用证据《{material.title}》已修订：{note}；相关陈述需复核",
                    refs=[material_id],
                )
            )
            if claim.status == ClaimStatus.VERIFIED:
                claim.status = ClaimStatus.PENDING
        corrections = []
        for story in self.stories.values():
            if story.status != "published" or not story.versions:
                continue
            hit = [c.id for c in affected if c.id in story.claim_ids]
            if hit:
                corrections.append(
                    self._add_correction(
                        story,
                        CorrectionKind.CORRECTION,
                        hit,
                        f"证据《{material.title}》修订：{note}",
                    )
                )
        return {
            "affected_claim_ids": [c.id for c in affected],
            "corrections": corrections,
        }

    # ---- 稿件与发布 ----

    def create_story(self, title, claim_ids, actor=None):
        if not title or not title.strip():
            raise ValidationError("稿件标题不能为空")
        for claim_id in claim_ids:
            self._claim(claim_id)
        story = Story(id=self._next_id("story"), title=title.strip(), claim_ids=list(claim_ids))
        self.stories[story.id] = story
        return story

    def publishable(self, story_id):
        """脱敏后的可发布视图：可发布叙事、证据缺口、引用来源。

        供编辑制作时间轴或地图稿使用；不包含讲述人联系方式。
        """
        story = self._story(story_id)
        statements, gaps, sources = [], [], {}
        for claim_id in story.claim_ids:
            claim = self.claims[claim_id]
            narrator = self.narrators[claim.narrator_id]
            if narrator.consent.fully_withdrawn:
                gaps.append({"claim_id": claim_id, "reason": "讲述人已撤回授权，素材不得继续使用"})
                continue
            if claim.status == ClaimStatus.PENDING:
                gaps.append({"claim_id": claim_id, "reason": "尚未作出核验决定"})
                continue
            if claim.status == ClaimStatus.RESTRICTED:
                gaps.append({"claim_id": claim_id, "reason": "编辑决定不宜公开"})
                continue
            statements.append(self._desensitized_statement(claim))
            for citation in claim.citations:
                if citation.material_id not in sources:
                    sources[citation.material_id] = self._source_entry(
                        self.materials[citation.material_id]
                    )
        return {
            "story_id": story.id,
            "title": story.title,
            "status": story.status,
            "statements": statements,
            "gaps": gaps,
            "sources": list(sources.values()),
        }

    def publish(self, story_id, actor):
        """刊发稿件：生成只读的脱敏快照版本。

        存在未核验陈述或已撤回授权的素材时拒绝刊发。
        """
        self._require_editor(actor)
        story = self._story(story_id)
        problems = []
        for claim_id in story.claim_ids:
            claim = self.claims[claim_id]
            narrator = self.narrators[claim.narrator_id]
            if narrator.consent.fully_withdrawn:
                problems.append(f"{claim_id}：讲述人已撤回授权")
            elif claim.status == ClaimStatus.PENDING:
                problems.append(f"{claim_id}：尚未作出核验决定")
        if problems:
            raise ValidationError("稿件暂不可发布；" + "；".join(problems))
        view = self.publishable(story_id)
        version = Version(
            number=len(story.versions) + 1,
            published_at=_now(),
            published_by=actor.get("id", ""),
            statements=copy.deepcopy(view["statements"]),
            gaps=copy.deepcopy(view["gaps"]),
        )
        story.versions.append(version)
        story.status = "published"
        return version

    def reader_corrections(self, story_id):
        """读者可见的更正 / 撤回记录，按当前授权脱敏，不含联系方式。"""
        story = self._story(story_id)
        out = []
        for corr in story.corrections:
            affected = []
            for claim_id in corr.affected_claim_ids:
                claim = self.claims.get(claim_id)
                if not claim:
                    continue
                st = self._desensitized_statement(claim)
                affected.append(
                    {
                        "claim_id": st["claim_id"],
                        "text": st["text"],
                        "years": st["years"],
                        "location": st["location"],
                        "narrator": st["narrator"],
                    }
                )
            out.append(
                {
                    "id": corr.id,
                    "version": corr.version,
                    "kind": corr.kind,
                    "kind_label": CORRECTION_LABELS[corr.kind],
                    "note": corr.note,
                    "at": corr.at,
                    "affected": affected,
                }
            )
        return out

    # ---- 内部 ----

    def _add_correction(self, story, kind, affected_claim_ids, note):
        correction = Correction(
            id=self._next_id("corr"),
            story_id=story.id,
            version=story.versions[-1].number,
            kind=kind,
            affected_claim_ids=list(affected_claim_ids),
            note=note,
            at=_now(),
        )
        story.corrections.append(correction)
        return correction

    def _desensitized_statement(self, claim):
        """按讲述人当前授权脱敏的单条陈述。"""
        narrator = self.narrators[claim.narrator_id]
        consent = narrator.consent
        name_level = consent.effective("name")
        if name_level == "public":
            narrator_field = narrator.name
        elif name_level == "pseudonym":
            narrator_field = _pseudonym(narrator.name)
        else:
            narrator_field = None
        location = None
        loc_level = consent.effective("location")
        if claim.location_candidates and loc_level != "internal":
            top = claim.location_candidates[0]
            location = top["name"] if loc_level == "precise" else top["county"]
        images = []
        for citation in claim.citations:
            material = self.materials.get(citation.material_id)
            if not material or material.type != MaterialType.IMAGE:
                continue
            owner = self.narrators.get(material.narrator_id)
            if owner and owner.consent.effective("image") == "public":
                images.append({"material_id": material.id, "fragment": citation.fragment})
        return {
            "claim_id": claim.id,
            "text": claim.text,
            "years": [claim.year_start, claim.year_end],
            "event": claim.event,
            "event_label": EVENT_LABELS.get(claim.event),
            "location": location,
            "narrator": narrator_field,
            "status": claim.status,
            "status_label": STATUS_LABELS[claim.status],
            "images": images,
            "citations": [
                {
                    "material_id": c.material_id,
                    "relation": c.relation,
                    "fragment": c.fragment,
                    "note": c.note,
                }
                for c in claim.citations
            ],
        }

    def _source_entry(self, material):
        """引用来源条目；档案与水文公开标题，口述与影像按授权脱敏。"""
        entry = {"material_id": material.id, "type": material.type}
        if material.type in (MaterialType.ARCHIVE, MaterialType.HYDROLOGY):
            entry["title"] = material.title
        elif material.type == MaterialType.IMAGE:
            owner = self.narrators.get(material.narrator_id)
            if owner and owner.consent.effective("image") == "public":
                entry["title"] = material.title
            else:
                entry["title"] = "影像素材（未授权公开）"
        else:
            entry["title"] = "口述访谈材料"
        return entry
