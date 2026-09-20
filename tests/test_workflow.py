"""核验工作流：决定权限、授权撤回、刊发版本与证据修订。"""

import copy
import unittest

from factcheck import hints, publish, workflow
from factcheck.demo import build_demo_store
from factcheck.errors import ConflictError


def verified_feature():
    """构造一个陈述已成立、专题已刊发的仓库。"""
    store, ids = build_demo_store()
    editor = ids["verifier"]
    workflow.add_citation(store, editor, ids["statement_a"], ids["hydrology"], "support")
    workflow.decide_statement(store, editor, ids["statement_a"], "verified")
    workflow.publish_feature(store, editor, ids["feature"])
    return store, ids


class DecisionTest(unittest.TestCase):
    def setUp(self):
        self.store, self.ids = build_demo_store()

    def test_decision_requires_verify_role(self):
        with self.assertRaises(PermissionError):
            workflow.decide_statement(self.store, "ed-0002", self.ids["statement_a"], "verified")
        with self.assertRaises(PermissionError):
            workflow.decide_statement(self.store, None, self.ids["statement_a"], "verified")
        with self.assertRaises(PermissionError):
            workflow.decide_statement(self.store, "ed-9999", self.ids["statement_a"], "verified")

    def test_decision_records_history(self):
        editor = self.ids["verifier"]
        workflow.decide_statement(self.store, editor, self.ids["statement_a"], "doubtful", "年份待核")
        workflow.decide_statement(self.store, editor, self.ids["statement_a"], "verified", "已比对水文记录")
        statement = self.store.get("statements", self.ids["statement_a"])
        self.assertEqual(statement["status"], "verified")
        self.assertEqual([d["status"] for d in statement["decisions"]], ["doubtful", "verified"])

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            workflow.decide_statement(
                self.store, self.ids["verifier"], self.ids["statement_a"], "pending"
            )
        with self.assertRaises(ValueError):
            workflow.decide_statement(
                self.store, self.ids["verifier"], self.ids["statement_a"], "maybe"
            )


class WithdrawalTest(unittest.TestCase):
    def test_withdrawal_blocks_draft_publish(self):
        store, ids = build_demo_store()
        editor = ids["verifier"]
        workflow.add_citation(store, editor, ids["statement_a"], ids["hydrology"], "support")
        workflow.decide_statement(store, editor, ids["statement_a"], "verified")
        workflow.withdraw_consent(store, ids["narrator_a"])
        with self.assertRaises(ConflictError):
            workflow.publish_feature(store, editor, ids["feature"])
        kinds = [g["kind"] for g in hints.feature_gaps(store, ids["feature"])]
        self.assertIn("consent_withdrawn", kinds)
        self.assertEqual(publish.timeline_items(store, ids["feature"]), [])

    def test_withdrawal_covers_material_cited_by_others(self):
        # 他人陈述引用了撤回者的影像证据，同样不得继续使用
        store, ids = build_demo_store()
        editor = ids["verifier"]
        workflow.add_citation(store, editor, ids["statement_a"], ids["image"], "context")
        workflow.decide_statement(store, editor, ids["statement_a"], "verified")
        workflow.withdraw_consent(store, ids["narrator_b"])
        blocked = hints.feature_gaps(store, ids["feature"])
        self.assertIn("consent_withdrawn", [g["kind"] for g in blocked])

    def test_withdrawal_on_published_keeps_version_and_adds_retraction(self):
        store, ids = verified_feature()
        snapshot_before = copy.deepcopy(store.get("features", ids["feature"])["versions"])
        result = workflow.withdraw_consent(store, ids["narrator_a"])
        self.assertEqual(len(result["retractions"]), 1)
        retraction = result["retractions"][0]
        self.assertEqual(retraction["kind"], "retraction")
        self.assertEqual(retraction["affected_statement_ids"], [ids["statement_a"]])
        # 已刊发版本保留当时依据，不被改写
        feature = store.get("features", ids["feature"])
        self.assertEqual(feature["versions"], snapshot_before)
        view = publish.published_view(store, ids["feature"])
        notices = {item["statement_id"]: item.get("reader_notice") for item in view["items"]}
        self.assertEqual(notices[ids["statement_a"]], "retraction")


class PublishTest(unittest.TestCase):
    def test_publish_requires_role_and_verified_statements(self):
        store, ids = build_demo_store()
        with self.assertRaises(PermissionError):
            workflow.publish_feature(store, "ed-0002", ids["feature"])
        with self.assertRaises(ConflictError):
            workflow.publish_feature(store, ids["verifier"], ids["feature"])

    def test_snapshot_is_immutable_after_correction(self):
        store, ids = verified_feature()
        editor = ids["verifier"]
        snapshot_before = copy.deepcopy(store.get("features", ids["feature"])["versions"])
        workflow.add_correction(
            store, editor, ids["feature"], [ids["statement_a"]], "引文页码勘误"
        )
        workflow.revise_evidence(
            store, editor, ids["hydrology"], {"content": "1958年7月洪峰过境。"}, "补充细节"
        )
        feature = store.get("features", ids["feature"])
        self.assertEqual(feature["versions"], snapshot_before)

    def test_republish_appends_new_version(self):
        store, ids = verified_feature()
        editor = ids["verifier"]
        workflow.add_citation(store, editor, ids["statement_b"], ids["archive"], "support")
        workflow.decide_statement(store, editor, ids["statement_b"], "verified")
        version = workflow.publish_feature(store, editor, ids["feature"])
        self.assertEqual(version["version"], 2)
        feature = store.get("features", ids["feature"])
        self.assertEqual(len(feature["versions"]), 2)
        self.assertEqual(len(feature["versions"][0]["items"]), 1)
        self.assertEqual(len(feature["versions"][1]["items"]), 2)

    def test_correction_requires_published_feature(self):
        store, ids = build_demo_store()
        with self.assertRaises(ConflictError):
            workflow.add_correction(
                store, ids["verifier"], ids["feature"], [ids["statement_a"]], "勘误"
            )

    def test_correction_rejects_foreign_statement(self):
        store, ids = verified_feature()
        other = workflow.register_statement(store, ids["narrator_a"], "另一段口述。")
        with self.assertRaises(ValueError):
            workflow.add_correction(
                store, ids["verifier"], ids["feature"], [other["id"]], "勘误"
            )


class EvidenceRevisionTest(unittest.TestCase):
    def test_revision_points_only_to_affected_statements(self):
        store, ids = verified_feature()
        editor = ids["verifier"]
        # 第二个专题刊发同一陈述（共用同一证据）
        other_feature = workflow.register_feature(store, "汛期专题", [ids["statement_a"]])
        workflow.publish_feature(store, editor, other_feature["id"])
        # 第三个专题仍是草稿，不应收到更正记录
        draft = workflow.register_feature(store, "未刊发专题", [ids["statement_a"]])

        result = workflow.revise_evidence(
            store, editor, ids["hydrology"],
            {"date_range": {"start": 1958, "end": 1958}}, "核定洪峰年份",
        )
        self.assertEqual(result["affected_statement_ids"], [ids["statement_a"]])
        self.assertEqual(
            sorted(result["features_notified"]),
            sorted([ids["feature"], other_feature["id"]]),
        )
        for feature_id in (ids["feature"], other_feature["id"]):
            corrections = store.corrections_for_feature(feature_id)
            self.assertEqual(len(corrections), 1)
            self.assertEqual(corrections[0]["affected_statement_ids"], [ids["statement_a"]])
        self.assertEqual(store.corrections_for_feature(draft["id"]), [])

    def test_revisions_keep_history(self):
        store, ids = build_demo_store()
        editor = ids["verifier"]
        workflow.revise_evidence(
            store, editor, ids["hydrology"], {"content": "修订后内容"}, "首次修订"
        )
        evidence = store.get("evidence", ids["hydrology"])
        self.assertEqual(evidence["content"], "修订后内容")
        self.assertEqual(evidence["revisions"][0]["before"]["content"], "1958年7月花园口站出现洪峰。")


if __name__ == "__main__":
    unittest.main()
