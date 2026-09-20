"""黄河叙事事实核验的服务入口。

提供 /health 健康检查与 /api/* 核验接口。需要编辑身份的动作
（核验决定、建立引用、刊发、更正、修订证据）通过请求头
X-Editor-Id 识别；本服务不含登录体系，部署时应置于内网或网关之后。
"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from factcheck import hints, publish, workflow
from factcheck.errors import ConflictError
from factcheck.store import Store

SERVICE_ID = "river-fact-check"
SERVICE_NAME = "黄河叙事事实核验"


def health_payload():
    """返回稳定的服务身份信息。"""
    return {"status": "ok", "service": SERVICE_ID, "name": SERVICE_NAME}


class Api:
    """把 HTTP 请求映射到核验工作流，并把业务异常转为状态码。"""

    def __init__(self, store):
        self.store = store

    def handle(self, method, path, body, editor_id):
        """返回 (状态码, 响应体)。body 为已解析的 JSON 对象。"""
        try:
            return self._dispatch(method, path, body or {}, editor_id)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except KeyError as exc:
            return 404, {"error": exc.args[0] if exc.args else "记录不存在"}
        except PermissionError as exc:
            return 403, {"error": str(exc)}
        except ConflictError as exc:
            return 409, {"error": str(exc)}

    def _dispatch(self, method, path, body, editor_id):
        for route_method, pattern, handler in ROUTES:
            if route_method != method:
                continue
            match = pattern.match(path)
            if match:
                return 200, handler(self, body, editor_id, **match.groupdict())
        return 404, {"error": f"未定义的路径：{method} {path}"}


def _route_health(api, body, editor_id):
    return health_payload()


def _route_create_editor(api, body, editor_id):
    return workflow.register_editor(api.store, body.get("name", ""), body.get("roles", []))


def _route_create_narrator(api, body, editor_id):
    return workflow.register_narrator(
        api.store, body.get("name", ""), body.get("contact", ""), body.get("consent")
    )


def _route_update_consent(api, body, editor_id, narrator_id):
    return workflow.update_consent(api.store, narrator_id, body.get("consent", {}))


def _route_withdraw(api, body, editor_id, narrator_id):
    return workflow.withdraw_consent(api.store, narrator_id)


def _route_create_evidence(api, body, editor_id):
    return workflow.register_evidence(
        api.store, body.get("type", ""), body.get("title", ""),
        content=body.get("content", ""), county=body.get("county"),
        date_range=body.get("date_range"), source=body.get("source"),
        narrator_id=body.get("narrator_id"),
    )


def _route_revise_evidence(api, body, editor_id, evidence_id):
    return workflow.revise_evidence(
        api.store, editor_id, evidence_id,
        body.get("updates", {}), body.get("reason", ""),
    )


def _route_create_statement(api, body, editor_id):
    return workflow.register_statement(
        api.store, body.get("narrator_id", ""), body.get("text", ""),
        event_time_range=body.get("event_time_range"),
        location_candidates=body.get("location_candidates"),
    )


def _route_add_citation(api, body, editor_id, statement_id):
    return workflow.add_citation(
        api.store, editor_id, statement_id,
        body.get("evidence_id", ""), body.get("relation", ""), body.get("note", ""),
    )


def _route_decide(api, body, editor_id, statement_id):
    return workflow.decide_statement(
        api.store, editor_id, statement_id,
        body.get("status", ""), body.get("note", ""),
    )


def _route_hints(api, body, editor_id, statement_id):
    return hints.statement_hints(api.store, statement_id)


def _route_create_feature(api, body, editor_id):
    return workflow.register_feature(
        api.store, body.get("title", ""), body.get("statement_ids")
    )


def _route_feature_add_statement(api, body, editor_id, feature_id):
    return workflow.add_statement_to_feature(api.store, feature_id, body.get("statement_id", ""))


def _route_feature_remove_statement(api, body, editor_id, feature_id):
    return workflow.remove_statement_from_feature(
        api.store, feature_id, body.get("statement_id", "")
    )


def _route_publish(api, body, editor_id, feature_id):
    return workflow.publish_feature(api.store, editor_id, feature_id)


def _route_timeline(api, body, editor_id, feature_id):
    return publish.timeline_view(api.store, feature_id)


def _route_map(api, body, editor_id, feature_id):
    return publish.map_view(api.store, feature_id)


def _route_gaps(api, body, editor_id, feature_id):
    return {"feature_id": feature_id, "gaps": hints.feature_gaps(api.store, feature_id)}


def _route_add_correction(api, body, editor_id, feature_id):
    return workflow.add_correction(
        api.store, editor_id, feature_id, body.get("statement_ids", []),
        body.get("reason", ""), body.get("kind", "correction"),
    )


def _route_reader_corrections(api, body, editor_id, feature_id):
    return {
        "feature_id": feature_id,
        "corrections": publish.reader_corrections(api.store, feature_id),
    }


def _route_published(api, body, editor_id, feature_id):
    return publish.published_view(api.store, feature_id)


ROUTES = [
    ("GET", re.compile(r"^/health$"), _route_health),
    ("POST", re.compile(r"^/api/editors$"), _route_create_editor),
    ("POST", re.compile(r"^/api/narrators$"), _route_create_narrator),
    ("POST", re.compile(r"^/api/narrators/(?P<narrator_id>[^/]+)/consent$"), _route_update_consent),
    ("POST", re.compile(r"^/api/narrators/(?P<narrator_id>[^/]+)/withdraw$"), _route_withdraw),
    ("POST", re.compile(r"^/api/evidence$"), _route_create_evidence),
    ("POST", re.compile(r"^/api/evidence/(?P<evidence_id>[^/]+)/revise$"), _route_revise_evidence),
    ("POST", re.compile(r"^/api/statements$"), _route_create_statement),
    ("POST", re.compile(r"^/api/statements/(?P<statement_id>[^/]+)/citations$"), _route_add_citation),
    ("POST", re.compile(r"^/api/statements/(?P<statement_id>[^/]+)/decision$"), _route_decide),
    ("GET", re.compile(r"^/api/statements/(?P<statement_id>[^/]+)/hints$"), _route_hints),
    ("POST", re.compile(r"^/api/features$"), _route_create_feature),
    ("POST", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/statements$"), _route_feature_add_statement),
    ("POST", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/statements/remove$"), _route_feature_remove_statement),
    ("POST", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/publish$"), _route_publish),
    ("GET", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/timeline$"), _route_timeline),
    ("GET", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/map$"), _route_map),
    ("GET", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/gaps$"), _route_gaps),
    ("POST", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/corrections$"), _route_add_correction),
    ("GET", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/corrections$"), _route_reader_corrections),
    ("GET", re.compile(r"^/api/features/(?P<feature_id>[^/]+)/published$"), _route_published),
]


class Handler(BaseHTTPRequestHandler):
    """提供健康检查与事实核验 API。api 由 create_server 注入。"""

    api = None

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._respond(400, {"error": "请求体不是有效 JSON"})
            return
        editor_id = self.headers.get("X-Editor-Id")
        status, payload = self.api.handle(method, self.path, body, editor_id)
        self._respond(status, payload)

    def _respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def create_server(port, store):
    """绑定 store 构造 HTTP 服务；port 为 0 时由系统分配端口。"""
    handler = type("BoundHandler", (Handler,), {"api": Api(store)})
    return ThreadingHTTPServer(("0.0.0.0", port), handler)


def main():
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", default="data/store.json", help="JSON 存储文件路径")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        assert health_payload()["service"] == SERVICE_ID
        Store()  # 仓库可空载构造
        print("基础检查通过")
        return
    store = Store(args.data)
    create_server(args.port, store).serve_forever()


if __name__ == "__main__":
    main()
