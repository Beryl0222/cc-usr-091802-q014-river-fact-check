"""脱敏发布视图：时间轴、地图、读者可见的刊发版本与更正记录。

本模块是内部记录通往外部的唯一出口：
- 只输出“成立”且授权有效的陈述；
- 姓名、位置、影像按讲述人授权范围脱敏；
- 讲述人联系方式等内部字段绝不进入任何视图。
"""

from .consent import blocked_statement_ids, is_withdrawn
from .errors import ConflictError
from .hints import feature_gaps

GRANULARITY_RANK = {"county": 0, "township": 1, "village": 2}
ANONYMOUS_LABEL = "匿名讲述人"


def _coarsen_location(location, granularity):
    """按授权粒度截断地点：县区必留，乡镇与具体地名按授权放行。"""
    rank = GRANULARITY_RANK[granularity]
    result = {"county": location["county"]}
    if rank >= GRANULARITY_RANK["township"] and location.get("township"):
        result["township"] = location["township"]
    if rank >= GRANULARITY_RANK["village"] and location.get("name"):
        result["name"] = location["name"]
    return result


def _public_narrator(narrator):
    if narrator["consent"]["name"] == "public":
        return narrator["name"]
    return ANONYMOUS_LABEL


def timeline_items(store, feature_id):
    """可发布叙事条目：仅成立且授权有效的陈述，按同意范围脱敏。"""
    feature = store.get("features", feature_id)
    blocked = set(blocked_statement_ids(store, feature_id))
    items = []
    for statement_id in feature["statement_ids"]:
        if statement_id in blocked:
            continue
        statement = store.get("statements", statement_id)
        if statement["status"] != "verified":
            continue
        narrator = store.get("narrators", statement["narrator_id"])
        granularity = narrator["consent"]["location"]
        images, sources = [], []
        for citation in store.citations_for_statement(statement_id):
            if not citation["confirmed"]:
                continue
            evidence = store.get("evidence", citation["evidence_id"])
            if evidence["type"] == "image":
                owner = store.get("narrators", evidence["narrator_id"])
                if not is_withdrawn(owner) and owner["consent"]["image"] == "public":
                    images.append({"evidence_id": evidence["id"], "title": evidence["title"]})
            elif evidence["type"] in ("archive", "hydrology"):
                sources.append({
                    "evidence_id": evidence["id"],
                    "type": evidence["type"],
                    "title": evidence["title"],
                    "source": evidence["source"],
                })
        items.append({
            "statement_id": statement_id,
            "text": statement["text"],
            "time_range": statement["event_time_range"],
            "locations": [
                _coarsen_location(loc, granularity)
                for loc in statement["location_candidates"]
            ],
            "narrator": _public_narrator(narrator),
            "images": images,
            "sources": sources,
        })
    items.sort(key=lambda item: (item["time_range"] or {"start": 9999})["start"])
    return items


def timeline_view(store, feature_id):
    """编辑制作时间轴用的视图：可发布叙事 + 证据缺口。"""
    feature = store.get("features", feature_id)
    return {
        "feature_id": feature["id"],
        "title": feature["title"],
        "items": timeline_items(store, feature_id),
        "gaps": feature_gaps(store, feature_id),
    }


def map_view(store, feature_id):
    """编辑制作地图稿用的视图：按脱敏后的地点归并条目。"""
    view = timeline_view(store, feature_id)
    grouped = {}
    for item in view["items"]:
        for location in (item["locations"] or [{"county": "地点待定"}]):
            key = tuple(sorted(location.items()))
            grouped.setdefault(key, {"location": location, "items": []})["items"].append(item)
    return {
        "feature_id": view["feature_id"],
        "title": view["title"],
        "locations": [grouped[key] for key in sorted(grouped)],
        "gaps": view["gaps"],
    }


def reader_corrections(store, feature_id):
    """读者可见的更正/撤回记录：说明更正了什么，不含内部人员信息。"""
    return [
        {
            "id": record["id"],
            "kind": record["kind"],
            "reason": record["reason"],
            "affected_statement_ids": record["affected_statement_ids"],
            "created_at": record["created_at"],
        }
        for record in store.corrections_for_feature(feature_id)
    ]


def published_view(store, feature_id):
    """读者视图：最新刊发版本（历史快照）加读者可见的更正记录。

    快照本身只读——更正与撤回以记录形式附加，受影响的条目
    标注 reader_notice，历史版本不被重写。
    """
    feature = store.get("features", feature_id)
    if not feature["versions"]:
        raise ConflictError("专题尚未刊发")
    latest = feature["versions"][-1]
    notices = {}
    for record in store.corrections_for_feature(feature_id):
        for statement_id in record["affected_statement_ids"]:
            notices[statement_id] = record["kind"]
    items = []
    for item in latest["items"]:
        entry = dict(item)
        if item["statement_id"] in notices:
            entry["reader_notice"] = notices[item["statement_id"]]
        items.append(entry)
    return {
        "feature_id": feature["id"],
        "title": feature["title"],
        "version": latest["version"],
        "published_at": latest["published_at"],
        "items": items,
        "corrections": reader_corrections(store, feature_id),
    }
