"""黄河叙事事实核验的服务入口与 HTTP 接口。"""

import argparse
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from factcheck.core import FactCheckService, NotFoundError, ValidationError
from factcheck.models import STATUS_LABELS

SERVICE_ID = "river-fact-check"
SERVICE_NAME = "黄河叙事事实核验"


def health_payload():
    """返回稳定的服务身份信息。"""
    return {"status": "ok", "service": SERVICE_ID, "name": SERVICE_NAME}


def load_gazetteer():
    """加载公开地名样例，用于旧地名到现址的候选匹配。"""
    path = Path(__file__).resolve().parent / "fixtures" / "gazetteer.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("gazetteer", [])


def build_service():
    return FactCheckService(gazetteer=load_gazetteer())


# ---- 视图序列化（任何响应都不包含讲述人联系方式） ----


def narrator_view(narrator):
    return {
        "id": narrator.id,
        "name": narrator.name,
        "consent": {
            "levels": dict(narrator.consent.levels),
            "withdrawn": list(narrator.consent.withdrawn),
        },
    }


def material_view(material):
    return asdict(material)


def claim_view(claim):
    return {
        "id": claim.id,
        "narrator_id": claim.narrator_id,
        "material_id": claim.material_id,
        "text": claim.text,
        "years": [claim.year_start, claim.year_end],
        "place_name": claim.place_name,
        "event": claim.event,
        "status": claim.status,
        "status_label": STATUS_LABELS[claim.status],
        "location_candidates": claim.location_candidates,
        "citations": [asdict(c) for c in claim.citations],
        "hints": [asdict(h) for h in claim.hints],
        "decisions": [asdict(d) for d in claim.decisions],
    }


def story_view(story):
    return {
        "id": story.id,
        "title": story.title,
        "status": story.status,
        "claim_ids": list(story.claim_ids),
        "version_count": len(story.versions),
    }


# ---- 路由 ----


def _segments(path):
    path = path.split("?", 1)[0]
    return [s for s in path.strip("/").split("/") if s]


def _match(pattern, segments):
    if len(pattern) != len(segments):
        return None
    params = {}
    for pat, seg in zip(pattern, segments):
        if pat.startswith("{"):
            params[pat[1:-1]] = seg
        elif pat != seg:
            return None
    return params


def _api_register_narrator(svc, body):
    narrator = svc.register_narrator(body["name"], body.get("contact", ""), body.get("consent"))
    return 201, narrator_view(narrator)


def _api_update_consent(svc, body, narrator_id):
    consent = svc.update_consent(narrator_id, body["scope"], body["level"])
    return 200, {"levels": dict(consent.levels), "withdrawn": list(consent.withdrawn)}


def _api_withdraw(svc, body, narrator_id):
    corrections = svc.withdraw(narrator_id, body.get("scope", "all"), body.get("note", ""))
    return 200, {"corrections": [asdict(c) for c in corrections]}


def _api_register_material(svc, body):
    material = svc.register_material(
        body["type"],
        body["title"],
        narrator_id=body.get("narrator_id"),
        year_start=body.get("year_start"),
        year_end=body.get("year_end"),
        place=body.get("place"),
        fragments=body.get("fragments"),
        records=body.get("records"),
    )
    return 201, material_view(material)


def _api_register_claim(svc, body):
    claim = svc.register_claim(
        body["narrator_id"],
        body["material_id"],
        body["text"],
        body["year_start"],
        body["year_end"],
        body["place_name"],
        event=body.get("event"),
    )
    return 201, claim_view(claim)


def _api_get_claim(svc, _body, claim_id):
    return 200, claim_view(svc._claim(claim_id))


def _api_add_citation(svc, body, claim_id):
    citation = svc.add_citation(
        claim_id,
        body["material_id"],
        body["relation"],
        note=body.get("note", ""),
        fragment=body.get("fragment"),
        actor=body.get("actor"),
    )
    return 201, asdict(citation)


def _api_decide(svc, body, claim_id):
    decision = svc.decide(claim_id, body.get("actor"), body["status"], body.get("rationale", ""))
    return 200, asdict(decision)


def _api_create_story(svc, body):
    story = svc.create_story(body["title"], body.get("claim_ids", []), body.get("actor"))
    return 201, story_view(story)


def _api_publishable(svc, _body, story_id):
    return 200, svc.publishable(story_id)


def _api_publish(svc, body, story_id):
    version = svc.publish(story_id, body.get("actor"))
    return 200, {"story_id": story_id, "version": asdict(version)}


def _api_reader_corrections(svc, _body, story_id):
    return 200, {"corrections": svc.reader_corrections(story_id)}


def _api_revise_evidence(svc, body, material_id):
    result = svc.revise_evidence(material_id, body["note"], body.get("actor"))
    return 200, {
        "affected_claim_ids": result["affected_claim_ids"],
        "corrections": [asdict(c) for c in result["corrections"]],
    }


ROUTES = [
    ("POST", ("api", "narrators"), _api_register_narrator),
    ("POST", ("api", "narrators", "{narrator_id}", "consent"), _api_update_consent),
    ("POST", ("api", "narrators", "{narrator_id}", "withdraw"), _api_withdraw),
    ("POST", ("api", "materials"), _api_register_material),
    ("POST", ("api", "materials", "{material_id}", "revisions"), _api_revise_evidence),
    ("POST", ("api", "claims"), _api_register_claim),
    ("GET", ("api", "claims", "{claim_id}"), _api_get_claim),
    ("POST", ("api", "claims", "{claim_id}", "citations"), _api_add_citation),
    ("POST", ("api", "claims", "{claim_id}", "decision"), _api_decide),
    ("POST", ("api", "stories"), _api_create_story),
    ("GET", ("api", "stories", "{story_id}", "publishable"), _api_publishable),
    ("POST", ("api", "stories", "{story_id}", "publish"), _api_publish),
    ("GET", ("api", "stories", "{story_id}", "corrections"), _api_reader_corrections),
]


def dispatch(service, method, path, body=None):
    """分发 API 请求，返回 (状态码, 响应体)。异常统一映射为错误响应。"""
    body = body or {}
    try:
        for route_method, pattern, handler in ROUTES:
            if route_method != method:
                continue
            params = _match(pattern, _segments(path))
            if params is not None:
                return handler(service, body, **params)
        return 404, {"error": f"未知接口：{method} {path}"}
    except ValidationError as exc:
        return 400, {"error": str(exc)}
    except PermissionError as exc:
        return 403, {"error": str(exc)}
    except NotFoundError as exc:
        return 404, {"error": str(exc)}
    except (KeyError, TypeError) as exc:
        return 400, {"error": f"请求参数不完整或不合法：{exc}"}


class Handler(BaseHTTPRequestHandler):
    """健康检查与事实核验 API。"""

    service = None

    def do_GET(self):
        if self.path == "/health":
            self._json(200, health_payload())
            return
        self._api("GET")

    def do_POST(self):
        self._api("POST")

    def _api(self, method):
        body = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._json(400, {"error": "请求体不是合法的 JSON"})
                    return
        status, payload = dispatch(self.service, method, self.path, body)
        self._json(status, payload)

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def main():
    parser = argparse.ArgumentParser(description=SERVICE_NAME)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        assert health_payload()["service"] == SERVICE_ID
        print("基础检查通过")
        return
    Handler.service = build_service()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
