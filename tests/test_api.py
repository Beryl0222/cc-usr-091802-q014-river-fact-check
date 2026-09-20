"""HTTP 接口层的行为测试（不经过真实网络，直接驱动 dispatch）。"""

import json
import unittest

from service import build_service, dispatch, health_payload

EDITOR = {"id": "ed-1", "role": "editor"}
ASSISTANT = {"id": "as-1", "role": "assistant"}
CONTACT = "13800000000"


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


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.svc = build_service()
        status, payload = dispatch(
            self.svc, "POST", "/api/narrators", {"name": "王守堤", "contact": CONTACT}
        )
        self.assertEqual(status, 201)
        self.narrator = payload
        status, payload = dispatch(
            self.svc,
            "POST",
            "/api/materials",
            {
                "type": "oral",
                "title": "王守堤口述（一）",
                "narrator_id": self.narrator["id"],
                "year_start": 1955,
                "year_end": 1960,
                "place": "花园口",
            },
        )
        self.assertEqual(status, 201)
        self.material = payload
        status, payload = dispatch(
            self.svc,
            "POST",
            "/api/claims",
            {
                "narrator_id": self.narrator["id"],
                "material_id": self.material["id"],
                "text": "1958年花园口发大水",
                "year_start": 1957,
                "year_end": 1959,
                "place_name": "花园口",
                "event": "flood",
            },
        )
        self.assertEqual(status, 201)
        self.claim = payload

    def test_health_payload(self):
        self.assertEqual(health_payload()["service"], "river-fact-check")

    def test_narrator_response_never_contains_contact(self):
        text = "\n".join(flatten(self.narrator))
        self.assertNotIn(CONTACT, text)
        self.assertNotIn("contact", text.lower())

    def test_claim_created_with_location_candidates_and_hints(self):
        self.assertEqual(self.claim["status"], "pending")
        self.assertTrue(self.claim["location_candidates"])
        self.assertEqual(self.claim["location_candidates"][0]["county"], "河南省郑州市惠济区")
        for hint in self.claim["hints"]:
            self.assertEqual(hint["generated_by"], "auto")

    def test_decision_requires_editor_role(self):
        path = f"/api/claims/{self.claim['id']}/decision"
        status, payload = dispatch(
            self.svc, "POST", path, {"actor": ASSISTANT, "status": "verified"}
        )
        self.assertEqual(status, 403)
        status, payload = dispatch(
            self.svc, "POST", path, {"actor": EDITOR, "status": "verified", "rationale": "水文吻合"}
        )
        self.assertEqual(status, 200)
        status, payload = dispatch(self.svc, "GET", f"/api/claims/{self.claim['id']}")
        self.assertEqual(payload["status"], "verified")
        self.assertEqual(payload["status_label"], "成立")

    def test_story_publishable_and_reader_corrections(self):
        dispatch(
            self.svc,
            "POST",
            f"/api/claims/{self.claim['id']}/decision",
            {"actor": EDITOR, "status": "verified"},
        )
        status, payload = dispatch(
            self.svc, "POST", "/api/stories", {"title": "花园口记忆", "claim_ids": [self.claim["id"]]}
        )
        self.assertEqual(status, 201)
        story_id = payload["id"]
        status, payload = dispatch(self.svc, "GET", f"/api/stories/{story_id}/publishable")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["statements"]), 1)
        status, payload = dispatch(
            self.svc, "POST", f"/api/stories/{story_id}/publish", {"actor": EDITOR}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"]["number"], 1)
        # 撤回后产生读者可见的撤回记录，且不包含联系方式
        status, payload = dispatch(
            self.svc, "POST", f"/api/narrators/{self.narrator['id']}/withdraw", {}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["corrections"][0]["kind"], "retraction")
        status, payload = dispatch(self.svc, "GET", f"/api/stories/{story_id}/corrections")
        self.assertEqual(status, 200)
        self.assertEqual(payload["corrections"][0]["kind_label"], "撤回")
        self.assertNotIn(CONTACT, json.dumps(payload, ensure_ascii=False))

    def test_error_mapping(self):
        status, _ = dispatch(self.svc, "GET", "/api/claims/claim-9999")
        self.assertEqual(status, 404)
        status, _ = dispatch(self.svc, "GET", "/api/nope")
        self.assertEqual(status, 404)
        status, _ = dispatch(self.svc, "POST", "/api/narrators", {"name": ""})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
