"""HTTP API：路由、状态码与编辑身份。"""

import json
import threading
import unittest
import urllib.request

from factcheck.demo import build_demo_store
from factcheck.store import Store
from service import SERVICE_ID, Api, create_server


class ApiRoutingTest(unittest.TestCase):
    def setUp(self):
        self.store, self.ids = build_demo_store()
        self.api = Api(self.store)
        self.editor = self.ids["verifier"]

    def call(self, method, path, body=None, editor=None):
        return self.api.handle(method, path, body or {}, editor)

    def test_health(self):
        status, payload = self.call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], SERVICE_ID)

    def test_unknown_path(self):
        status, payload = self.call("GET", "/api/nope")
        self.assertEqual(status, 404)

    def test_missing_record(self):
        status, _ = self.call("GET", "/api/statements/st-9999/hints", editor=self.editor)
        self.assertEqual(status, 404)

    def test_decision_requires_editor_header(self):
        path = f"/api/statements/{self.ids['statement_a']}/decision"
        status, _ = self.call("POST", path, {"status": "verified"})
        self.assertEqual(status, 403)

    def test_invalid_body_rejected(self):
        status, _ = self.call(
            "POST", f"/api/statements/{self.ids['statement_a']}/decision",
            {"status": "maybe"}, editor=self.editor,
        )
        self.assertEqual(status, 400)

    def test_full_editorial_flow(self):
        ed = self.editor
        sa = self.ids["statement_a"]
        status, citation = self.call(
            "POST", f"/api/statements/{sa}/citations",
            {"evidence_id": self.ids["hydrology"], "relation": "support"}, editor=ed,
        )
        self.assertEqual(status, 200)
        status, _ = self.call(
            "POST", f"/api/statements/{sa}/decision", {"status": "verified"}, editor=ed
        )
        self.assertEqual(status, 200)
        status, version = self.call(
            "POST", f"/api/features/{self.ids['feature']}/publish", editor=ed
        )
        self.assertEqual(status, 200)
        self.assertEqual(version["version"], 1)
        status, view = self.call("GET", f"/api/features/{self.ids['feature']}/timeline")
        self.assertEqual(status, 200)
        self.assertEqual(len(view["items"]), 1)
        self.assertEqual(view["items"][0]["narrator"], "匿名讲述人")

    def test_withdrawal_then_publish_conflict(self):
        ed = self.editor
        sa = self.ids["statement_a"]
        self.call("POST", f"/api/statements/{sa}/citations",
                  {"evidence_id": self.ids["hydrology"], "relation": "support"}, editor=ed)
        self.call("POST", f"/api/statements/{sa}/decision", {"status": "verified"}, editor=ed)
        status, result = self.call("POST", f"/api/narrators/{self.ids['narrator_a']}/withdraw")
        self.assertEqual(status, 200)
        status, payload = self.call(
            "POST", f"/api/features/{self.ids['feature']}/publish", editor=ed
        )
        self.assertEqual(status, 409)


class HttpServerTest(unittest.TestCase):
    def setUp(self):
        self.server = create_server(0, Store())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_health_over_http(self):
        self.assertEqual(self.get("/health")["service"], SERVICE_ID)

    def test_404_over_http(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/features/ft-0001/timeline")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
