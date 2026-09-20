"""脱敏发布视图：时间轴、地图、读者更正与隐私边界。"""

import json
import unittest

from factcheck import publish, workflow
from factcheck.demo import build_demo_store


def verified_store():
    store, ids = build_demo_store()
    editor = ids["verifier"]
    # narrator_a 未授权影像公开；其影像被本人陈述引用
    image_a = workflow.register_evidence(
        store, "image", "打谷场旧照", county="惠济区", narrator_id=ids["narrator_a"]
    )
    ids["image_a"] = image_a["id"]
    workflow.add_citation(store, editor, ids["statement_a"], ids["hydrology"], "support")
    workflow.add_citation(store, editor, ids["statement_a"], image_a["id"], "context")
    workflow.decide_statement(store, editor, ids["statement_a"], "verified")
    workflow.add_citation(store, editor, ids["statement_b"], ids["archive"], "support")
    workflow.add_citation(store, editor, ids["statement_b"], ids["image"], "context")
    workflow.decide_statement(store, editor, ids["statement_b"], "verified")
    return store, ids


class DesensitizationTest(unittest.TestCase):
    def setUp(self):
        self.store, self.ids = verified_store()
        self.items = {
            item["statement_id"]: item
            for item in publish.timeline_items(self.store, self.ids["feature"])
        }

    def test_anonymous_narrator_by_default(self):
        item = self.items[self.ids["statement_a"]]
        self.assertEqual(item["narrator"], "匿名讲述人")

    def test_public_name_when_consented(self):
        item = self.items[self.ids["statement_b"]]
        self.assertEqual(item["narrator"], "刘渡工")

    def test_location_coarsened_to_county(self):
        item = self.items[self.ids["statement_a"]]
        self.assertEqual(item["locations"], [{"county": "惠济区"}])

    def test_location_keeps_township_when_consented(self):
        item = self.items[self.ids["statement_b"]]
        self.assertEqual(item["locations"], [{"county": "中牟县", "township": "渡口镇"}])

    def test_image_hidden_without_consent(self):
        # statement_a 的讲述人未授权影像公开
        self.assertEqual(self.items[self.ids["statement_a"]]["images"], [])

    def test_image_shown_when_consented(self):
        images = self.items[self.ids["statement_b"]]["images"]
        self.assertEqual([img["evidence_id"] for img in images], [self.ids["image"]])

    def test_sources_only_from_public_records(self):
        sources = self.items[self.ids["statement_b"]]["sources"]
        self.assertEqual([s["evidence_id"] for s in sources], [self.ids["archive"]])
        self.assertEqual(sources[0]["source"], "县志数字化公开版")

    def test_contact_never_leaks(self):
        feature_id = self.ids["feature"]
        workflow.publish_feature(self.store, self.ids["verifier"], feature_id)
        views = [
            publish.timeline_view(self.store, feature_id),
            publish.map_view(self.store, feature_id),
            publish.published_view(self.store, feature_id),
            publish.reader_corrections(self.store, feature_id),
        ]
        for view in views:
            payload = json.dumps(view, ensure_ascii=False)
            self.assertNotIn("internal-contact", payload)
            self.assertNotIn("contact", payload)


class GapTest(unittest.TestCase):
    def test_gaps_cover_pending_and_missing_support(self):
        store, ids = build_demo_store()
        editor = ids["verifier"]
        workflow.decide_statement(store, editor, ids["statement_a"], "verified")
        gaps = {g["statement_id"]: g["kind"] for g in publish.timeline_view(store, ids["feature"])["gaps"]}
        self.assertEqual(gaps[ids["statement_a"]], "missing_support")
        self.assertEqual(gaps[ids["statement_b"]], "undecided")

    def test_restricted_statement_excluded_from_items(self):
        store, ids = build_demo_store()
        editor = ids["verifier"]
        workflow.decide_statement(store, editor, ids["statement_a"], "restricted")
        view = publish.timeline_view(store, ids["feature"])
        self.assertEqual(view["items"], [])
        kinds = [g["kind"] for g in view["gaps"]]
        self.assertIn("restricted", kinds)


class MapViewTest(unittest.TestCase):
    def test_items_grouped_by_coarsened_location(self):
        store, ids = verified_store()
        view = publish.map_view(store, ids["feature"])
        counties = [loc["location"]["county"] for loc in view["locations"]]
        self.assertEqual(counties, ["中牟县", "惠济区"])
        for loc in view["locations"]:
            self.assertTrue(loc["items"])


class ReaderViewTest(unittest.TestCase):
    def test_published_view_marks_corrected_items(self):
        store, ids = verified_store()
        editor = ids["verifier"]
        workflow.publish_feature(store, editor, ids["feature"])
        workflow.add_correction(
            store, editor, ids["feature"], [ids["statement_a"]], "年份表述勘误"
        )
        view = publish.published_view(store, ids["feature"])
        notices = {item["statement_id"]: item.get("reader_notice") for item in view["items"]}
        self.assertEqual(notices[ids["statement_a"]], "correction")
        self.assertIsNone(notices[ids["statement_b"]])
        self.assertEqual(view["corrections"][0]["reason"], "年份表述勘误")
        self.assertNotIn("created_by", view["corrections"][0])


if __name__ == "__main__":
    unittest.main()
