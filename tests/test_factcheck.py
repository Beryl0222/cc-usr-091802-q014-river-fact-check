"""事实核验模块的行为测试。

覆盖：引用建立、自动提示（只提示不决定）、编辑决定权限、授权与撤回、
发布快照只读、更正 / 撤回记录、脱敏视图与联系方式保护。
"""

import copy
import unittest
from types import SimpleNamespace

from factcheck.core import FactCheckService, NotFoundError, ValidationError
from factcheck.models import ClaimStatus, CorrectionKind, HintKind, MaterialType, Relation

EDITOR = {"id": "ed-1", "role": "editor"}
ASSISTANT = {"id": "as-1", "role": "assistant"}

GAZETTEER = [
    {"old": "花园口", "current": "河南省郑州市惠济区花园口镇", "county": "河南省郑州市惠济区"},
    {"old": "东坝头", "current": "河南省开封市兰考县东坝头镇", "county": "河南省开封市兰考县"},
]

CONTACTS = ("13800000000", "13900000000")


def make_service():
    """构造一个包含两位讲述人、口述 / 水文 / 影像 / 档案素材的服务。"""
    svc = FactCheckService(gazetteer=GAZETTEER)
    ids = SimpleNamespace()
    ids.nar1 = svc.register_narrator(
        "王守堤", CONTACTS[0], {"name": "pseudonym", "location": "county", "image": "internal"}
    ).id
    ids.nar2 = svc.register_narrator(
        "李渡口", CONTACTS[1], {"name": "public", "location": "precise", "image": "public"}
    ).id
    ids.oral1 = svc.register_material(
        MaterialType.ORAL,
        "王守堤口述（一）",
        narrator_id=ids.nar1,
        year_start=1955,
        year_end=1960,
        place="花园口",
        fragments=[{"id": "seg-1", "note": "1958年洪水回忆"}],
    ).id
    ids.oral2 = svc.register_material(
        MaterialType.ORAL,
        "李渡口口述（一）",
        narrator_id=ids.nar2,
        year_start=1956,
        year_end=1959,
        place="花园口",
        fragments=[{"id": "seg-2", "note": "大水到村口"}],
    ).id
    ids.hydro = svc.register_material(
        MaterialType.HYDROLOGY,
        "花园口水文站洪峰记录",
        place="花园口",
        records=[
            {"year": 1938, "event": "breach"},
            {"year": 1958, "event": "flood"},
            {"year": 1982, "event": "flood"},
        ],
    ).id
    ids.image_public = svc.register_material(
        MaterialType.IMAGE,
        "花园口老照片",
        narrator_id=ids.nar2,
        year_start=1958,
        year_end=1958,
        place="花园口",
        fragments=[{"id": "img-1", "note": "堤岸合影"}],
    ).id
    ids.image_private = svc.register_material(
        MaterialType.IMAGE,
        "王守堤家老照片",
        narrator_id=ids.nar1,
        year_start=1958,
        year_end=1958,
        place="花园口",
        fragments=[{"id": "img-9", "note": "院墙水痕"}],
    ).id
    ids.archive = svc.register_material(
        MaterialType.ARCHIVE,
        "郑州专区治河档案",
        place="花园口",
        records=[{"year": 1958, "event": "flood", "note": "防汛通报"}],
    ).id
    return svc, ids


def flatten(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield str(key)
            yield from flatten(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            yield from flatten(value)
    else:
        yield str(payload)


class ContactGuardMixin:
    def assertNoContact(self, payload):
        text = "\n".join(flatten(payload))
        for contact in CONTACTS:
            self.assertNotIn(contact, text)
        self.assertNotIn("contact", text.lower())


class LocationAndHintTest(unittest.TestCase):
    def test_old_place_name_resolves_to_candidates(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        self.assertEqual(claim.location_candidates[0]["county"], "河南省郑州市惠济区")
        self.assertEqual(claim.location_candidates[0]["score"], 1.0)

    def test_unresolved_old_place_name_raises_hint(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "无名渡旧事", 1950, 1955, "无名渡")
        self.assertEqual(claim.location_candidates, [])
        kinds = {h.kind for h in claim.hints}
        self.assertIn(HintKind.PLACE_UNRESOLVED, kinds)

    def test_contradiction_hint_when_records_outside_claimed_range(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1963年花园口发大水", 1960, 1965, "花园口", event="flood")
        contradictions = [h for h in claim.hints if h.kind == HintKind.CONTRADICTION]
        self.assertTrue(contradictions)
        self.assertIn(ids.hydro, contradictions[0].refs)
        # 自动能力只提示，不改变核验状态
        self.assertEqual(claim.status, ClaimStatus.PENDING)
        self.assertEqual(claim.decisions, [])

    def test_similar_hint_when_records_inside_claimed_range(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        similar = [h for h in claim.hints if h.kind == HintKind.SIMILAR]
        refs = {ref for h in similar for ref in h.refs}
        self.assertIn(ids.hydro, refs)
        self.assertIn(ids.archive, refs)
        self.assertFalse([h for h in claim.hints if h.kind == HintKind.CONTRADICTION])

    def test_cross_narrator_similar_hint(self):
        svc, ids = make_service()
        claim1 = svc.register_claim(ids.nar1, ids.oral1, "1958年洪水到村口", 1957, 1959, "花园口", event="flood")
        claim2 = svc.register_claim(ids.nar2, ids.oral2, "1958年堤岸抢险", 1958, 1958, "花园口", event="flood")
        for claim, other in ((claim1, claim2), (claim2, claim1)):
            similar = [h for h in claim.hints if h.kind == HintKind.SIMILAR]
            self.assertIn(other.id, {ref for h in similar for ref in h.refs})

    def test_image_fragment_similar_hint(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年洪水到村口", 1957, 1959, "花园口", event="flood")
        similar = [h for h in claim.hints if h.kind == HintKind.SIMILAR]
        refs = {ref for h in similar for ref in h.refs}
        self.assertIn(ids.image_public, refs)
        self.assertIn("img-1", refs)


class CitationTest(unittest.TestCase):
    def test_editor_builds_citations_to_fragments_and_records(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        c1 = svc.add_citation(claim.id, ids.hydro, Relation.SUPPORTS, note="1958年洪峰", actor=EDITOR)
        c2 = svc.add_citation(claim.id, ids.image_public, Relation.CONTEXT, fragment="img-1", actor=EDITOR)
        self.assertEqual([c.relation for c in claim.citations], [Relation.SUPPORTS, Relation.CONTEXT])
        self.assertEqual(c2.fragment, "img-1")
        self.assertEqual(c1.created_by, EDITOR["id"])

    def test_invalid_relation_and_unknown_fragment_rejected(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        with self.assertRaises(ValidationError):
            svc.add_citation(claim.id, ids.hydro, "maybe")
        with self.assertRaises(ValidationError):
            svc.add_citation(claim.id, ids.image_public, Relation.SUPPORTS, fragment="img-x")
        with self.assertRaises(NotFoundError):
            svc.add_citation(claim.id, "mat-9999", Relation.SUPPORTS)


class DecisionPermissionTest(unittest.TestCase):
    def test_only_editor_can_decide(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        with self.assertRaises(PermissionError):
            svc.decide(claim.id, ASSISTANT, ClaimStatus.VERIFIED)
        with self.assertRaises(PermissionError):
            svc.decide(claim.id, None, ClaimStatus.VERIFIED)
        self.assertEqual(claim.status, ClaimStatus.PENDING)

    def test_editor_decision_is_logged(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        svc.decide(claim.id, EDITOR, ClaimStatus.QUESTIONABLE, "水文记录仅部分吻合")
        self.assertEqual(claim.status, ClaimStatus.QUESTIONABLE)
        self.assertEqual(claim.decisions[-1].editor_id, EDITOR["id"])
        with self.assertRaises(ValidationError):
            svc.decide(claim.id, EDITOR, "maybe")


class PublishableViewTest(ContactGuardMixin, unittest.TestCase):
    def _ready_story(self):
        svc, ids = make_service()
        c1 = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水，村子淹了一半", 1957, 1959, "花园口", event="flood")
        c2 = svc.register_claim(ids.nar2, ids.oral2, "1958年洪水漫过堤岸", 1958, 1958, "花园口", event="flood")
        svc.add_citation(c1.id, ids.hydro, Relation.SUPPORTS, note="1958年洪峰", actor=EDITOR)
        svc.add_citation(c1.id, ids.image_private, Relation.CONTEXT, fragment="img-9", actor=EDITOR)
        svc.add_citation(c2.id, ids.image_public, Relation.SUPPORTS, fragment="img-1", actor=EDITOR)
        svc.decide(c1.id, EDITOR, ClaimStatus.VERIFIED, "水文记录吻合")
        svc.decide(c2.id, EDITOR, ClaimStatus.VERIFIED, "影像佐证")
        story = svc.create_story("花园口记忆", [c1.id, c2.id])
        return svc, ids, story, (c1, c2)

    def test_desensitized_narrative_gaps_and_sources(self):
        svc, ids, story, (c1, c2) = self._ready_story()
        view = svc.publishable(story.id)
        st1, st2 = view["statements"]
        # 姓名按授权脱敏：化名 / 公开
        self.assertEqual(st1["narrator"], "王某")
        self.assertEqual(st2["narrator"], "李渡口")
        # 位置按授权脱敏：县级 / 精确
        self.assertEqual(st1["location"], "河南省郑州市惠济区")
        self.assertEqual(st2["location"], "河南省郑州市惠济区花园口镇")
        # 影像按授权脱敏：internal 的素材不出现，public 的出现
        self.assertEqual(st1["images"], [])
        self.assertEqual(st2["images"], [{"material_id": ids.image_public, "fragment": "img-1"}])
        # 引用来源：档案与水文公开标题，未授权影像脱敏
        sources = {s["material_id"]: s for s in view["sources"]}
        self.assertEqual(sources[ids.hydro]["title"], "花园口水文站洪峰记录")
        self.assertEqual(sources[ids.image_private]["title"], "影像素材（未授权公开）")
        self.assertEqual(sources[ids.image_public]["title"], "花园口老照片")
        self.assertEqual(view["gaps"], [])
        self.assertNoContact(view)

    def test_pending_and_restricted_claims_become_gaps(self):
        svc, ids = make_service()
        c1 = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        c2 = svc.register_claim(ids.nar2, ids.oral2, "某件不宜公开的事", 1958, 1958, "花园口")
        svc.decide(c2.id, EDITOR, ClaimStatus.RESTRICTED, "涉及家庭住址")
        story = svc.create_story("花园口记忆", [c1.id, c2.id])
        view = svc.publishable(story.id)
        reasons = {g["claim_id"]: g["reason"] for g in view["gaps"]}
        self.assertEqual(reasons[c1.id], "尚未作出核验决定")
        self.assertEqual(reasons[c2.id], "编辑决定不宜公开")
        self.assertEqual(view["statements"], [])


class PublishTest(unittest.TestCase):
    def test_publish_requires_decisions_and_editor_role(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        story = svc.create_story("花园口记忆", [claim.id])
        with self.assertRaises(ValidationError):
            svc.publish(story.id, EDITOR)  # 未核验
        svc.decide(claim.id, EDITOR, ClaimStatus.QUESTIONABLE, "仅部分吻合")
        with self.assertRaises(PermissionError):
            svc.publish(story.id, ASSISTANT)
        version = svc.publish(story.id, EDITOR)
        self.assertEqual(version.number, 1)
        self.assertEqual(version.statements[0]["status"], ClaimStatus.QUESTIONABLE)
        self.assertEqual(version.statements[0]["status_label"], "存疑")
        self.assertEqual(story.status, "published")


class WithdrawalTest(ContactGuardMixin, unittest.TestCase):
    def test_full_withdrawal_blocks_unpublished_story(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        svc.decide(claim.id, EDITOR, ClaimStatus.VERIFIED)
        story = svc.create_story("花园口记忆", [claim.id])
        svc.withdraw(ids.nar1)
        view = svc.publishable(story.id)
        self.assertEqual(view["statements"], [])
        self.assertIn("撤回", view["gaps"][0]["reason"])
        with self.assertRaises(ValidationError):
            svc.publish(story.id, EDITOR)

    def test_withdrawal_on_published_story_keeps_version_and_marks_retraction(self):
        svc, ids = make_service()
        claim = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        svc.decide(claim.id, EDITOR, ClaimStatus.VERIFIED)
        story = svc.create_story("花园口记忆", [claim.id])
        svc.publish(story.id, EDITOR)
        snapshot = copy.deepcopy(story.versions[0].statements)

        corrections = svc.withdraw(ids.nar1, note="讲述人要求撤回")
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].kind, CorrectionKind.RETRACTION)
        self.assertEqual(corrections[0].affected_claim_ids, [claim.id])
        self.assertEqual(corrections[0].version, 1)
        # 已刊发版本保留当时依据，不被重写
        self.assertEqual(story.versions[0].statements, snapshot)

        reader = svc.reader_corrections(story.id)
        self.assertEqual(reader[0]["kind_label"], "撤回")
        self.assertEqual(reader[0]["affected"][0]["claim_id"], claim.id)
        # 撤回后读者视图按当前授权脱敏
        self.assertIsNone(reader[0]["affected"][0]["narrator"])
        self.assertNoContact(reader)

    def test_scope_withdrawal_only_marks_stories_that_exposed_it(self):
        svc, ids = make_service()
        c1 = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        c2 = svc.register_claim(ids.nar2, ids.oral2, "1958年洪水漫过堤岸", 1958, 1958, "花园口", event="flood")
        svc.add_citation(c2.id, ids.image_public, Relation.SUPPORTS, fragment="img-1", actor=EDITOR)
        svc.decide(c1.id, EDITOR, ClaimStatus.VERIFIED)
        svc.decide(c2.id, EDITOR, ClaimStatus.VERIFIED)
        story = svc.create_story("花园口记忆", [c1.id, c2.id])
        svc.publish(story.id, EDITOR)

        # 撤回影像授权：刊发版本公开了 img-1，产生撤回记录
        corrections = svc.withdraw(ids.nar2, scope="image")
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0].affected_claim_ids, [c2.id])
        # 撤回姓名授权：nar1 刊发时只是化名、nar2 姓名公开过
        corrections = svc.withdraw(ids.nar1, scope="name")
        self.assertEqual(len(corrections), 1)  # 化名也算公开了姓名范畴
        # 影像撤回后，新的可发布视图不再包含影像
        view = svc.publishable(story.id)
        st2 = [s for s in view["statements"] if s["claim_id"] == c2.id][0]
        self.assertEqual(st2["images"], [])


class EvidenceRevisionTest(unittest.TestCase):
    def test_revision_marks_only_affected_statements_across_stories(self):
        svc, ids = make_service()
        c1 = svc.register_claim(ids.nar1, ids.oral1, "1958年花园口发大水", 1957, 1959, "花园口", event="flood")
        c2 = svc.register_claim(ids.nar2, ids.oral2, "1958年洪水漫过堤岸", 1958, 1958, "花园口", event="flood")
        c3 = svc.register_claim(ids.nar2, ids.oral2, "1956年修堤记工", 1956, 1956, "花园口")
        svc.add_citation(c1.id, ids.archive, Relation.SUPPORTS, actor=EDITOR)
        svc.add_citation(c2.id, ids.archive, Relation.SUPPORTS, actor=EDITOR)
        for claim in (c1, c2, c3):
            svc.decide(claim.id, EDITOR, ClaimStatus.VERIFIED)
        story1 = svc.create_story("专题一", [c1.id])
        story2 = svc.create_story("专题二", [c2.id, c3.id])
        svc.publish(story1.id, EDITOR)
        svc.publish(story2.id, EDITOR)
        snap1 = copy.deepcopy(story1.versions[0].statements)
        snap2 = copy.deepcopy(story2.versions[0].statements)

        with self.assertRaises(PermissionError):
            svc.revise_evidence(ids.archive, "档案年份勘误", ASSISTANT)

        result = svc.revise_evidence(ids.archive, "档案年份勘误：1958年应为1959年", EDITOR)
        self.assertEqual(set(result["affected_claim_ids"]), {c1.id, c2.id})
        # 同一证据被多个专题采用：各自只指出受影响的陈述
        self.assertEqual(story1.corrections[0].affected_claim_ids, [c1.id])
        self.assertEqual(story2.corrections[0].affected_claim_ids, [c2.id])
        self.assertEqual(story1.corrections[0].kind, CorrectionKind.CORRECTION)
        # 历史版本不被重写
        self.assertEqual(story1.versions[0].statements, snap1)
        self.assertEqual(story2.versions[0].statements, snap2)
        # 相关陈述退回待核验并留有提示
        self.assertEqual(svc.claims[c1.id].status, ClaimStatus.PENDING)
        kinds = {h.kind for h in svc.claims[c1.id].hints}
        self.assertIn(HintKind.EVIDENCE_REVISED, kinds)
        # 未引用该证据的陈述不受影响
        self.assertEqual(svc.claims[c3.id].status, ClaimStatus.VERIFIED)
        gaps = svc.publishable(story1.id)["gaps"]
        self.assertEqual(gaps[0]["reason"], "尚未作出核验决定")


if __name__ == "__main__":
    unittest.main()
