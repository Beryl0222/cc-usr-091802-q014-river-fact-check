"""自动提示：矛盾、相似线索与复核提示。"""

import unittest

from factcheck import hints, workflow
from factcheck.demo import build_demo_store


class ContradictionTest(unittest.TestCase):
    def setUp(self):
        self.store, self.ids = build_demo_store()
        self.editor = self.ids["verifier"]

    def test_time_conflict_when_ranges_disjoint(self):
        # 陈述称 1958-1959 年，却引用了 1964 年的县志记录
        workflow.add_citation(
            self.store, self.editor, self.ids["statement_a"], self.ids["archive"], "context"
        )
        found = hints.contradictions(self.store, self.ids["statement_a"])
        self.assertEqual([f["kind"] for f in found], ["time_conflict", "location_conflict"])

    def test_no_conflict_when_time_overlaps(self):
        workflow.add_citation(
            self.store, self.editor, self.ids["statement_a"], self.ids["hydrology"], "support"
        )
        self.assertEqual(hints.contradictions(self.store, self.ids["statement_a"]), [])

    def test_unconfirmed_citation_does_not_raise_conflict(self):
        citation = workflow.add_citation(
            self.store, self.editor, self.ids["statement_a"], self.ids["archive"], "context"
        )
        citation["confirmed"] = False  # 系统建议尚未确认
        self.assertEqual(hints.contradictions(self.store, self.ids["statement_a"]), [])


class SimilarityTest(unittest.TestCase):
    def setUp(self):
        self.store, self.ids = build_demo_store()

    def test_similar_by_shared_county_and_time(self):
        other = workflow.register_statement(
            self.store, self.ids["narrator_b"],
            "1958年大堤决口，村里组织抢险。",
            event_time_range={"start": 1958, "end": 1958},
            location_candidates=[{"county": "惠济区"}],
        )
        found = hints.similar_statements(self.store, self.ids["statement_a"])
        self.assertIn(other["id"], [f["statement_id"] for f in found])

    def test_similar_by_text_without_location(self):
        other = workflow.register_statement(
            self.store, self.ids["narrator_b"],
            "1958年秋天，村北的堤决了口，水漫到打谷场边。",
        )
        found = hints.similar_statements(self.store, self.ids["statement_a"])
        self.assertIn(other["id"], [f["statement_id"] for f in found])

    def test_suggested_evidence_excludes_already_cited(self):
        suggested = hints.suggested_evidence(self.store, self.ids["statement_a"])
        self.assertIn(self.ids["hydrology"], [s["evidence_id"] for s in suggested])
        workflow.add_citation(
            self.store, self.ids["verifier"], self.ids["statement_a"],
            self.ids["hydrology"], "support",
        )
        suggested = hints.suggested_evidence(self.store, self.ids["statement_a"])
        self.assertNotIn(self.ids["hydrology"], [s["evidence_id"] for s in suggested])


class ReviewFlagTest(unittest.TestCase):
    def test_flag_when_evidence_revised_after_decision(self):
        store, ids = build_demo_store()
        editor = ids["verifier"]
        workflow.add_citation(store, editor, ids["statement_a"], ids["hydrology"], "support")
        workflow.decide_statement(store, editor, ids["statement_a"], "verified",
                                  now="2026-09-01T00:00:00+00:00")
        self.assertEqual(hints.review_flags(store, ids["statement_a"]), [])
        workflow.revise_evidence(
            store, editor, ids["hydrology"],
            {"date_range": {"start": 1958, "end": 1958}}, "校对刊误",
            now="2026-09-02T00:00:00+00:00",
        )
        flags = hints.review_flags(store, ids["statement_a"])
        self.assertEqual([f["kind"] for f in flags], ["evidence_revised"])


class ReadOnlyTest(unittest.TestCase):
    def test_hints_never_change_statement_status(self):
        store, ids = build_demo_store()
        hints.statement_hints(store, ids["statement_a"])
        hints.feature_gaps(store, ids["feature"])
        statement = store.get("statements", ids["statement_a"])
        self.assertEqual(statement["status"], "pending")
        self.assertEqual(statement["decisions"], [])


if __name__ == "__main__":
    unittest.main()
