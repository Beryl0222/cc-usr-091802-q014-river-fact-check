"""领域记录的构造与校验。

所有记录都是可直接 JSON 序列化的字典，字段即存储格式，
避免在内存对象与持久化表示之间来回转换。记录一旦写入仓库，
只允许通过 workflow 中的业务动作修改。
"""

from datetime import datetime, timezone

EVIDENCE_TYPES = ("oral", "image", "archive", "hydrology")
STATEMENT_STATUS = ("pending", "verified", "doubtful", "restricted")
DECIDABLE_STATUS = ("verified", "doubtful", "restricted")
LOCATION_GRANULARITY = ("county", "township", "village")
NAME_SCOPE = ("anonymous", "public")
IMAGE_SCOPE = ("none", "public")
RELATIONS = ("support", "contradict", "context")
CORRECTION_KINDS = ("correction", "retraction")
EDITOR_ROLES = ("verify", "publish")

# 默认授权取最严格口径：匿名、位置只到县区、影像不公开。
DEFAULT_CONSENT = {"name": "anonymous", "location": "county", "image": "none"}


def utcnow():
    """返回带时区的当前时间（ISO 格式），字符串可直接按时间先后比较。"""
    return datetime.now(timezone.utc).isoformat()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_consent(consent):
    """把部分授权合并到最严格默认值上，并校验取值。"""
    merged = dict(DEFAULT_CONSENT)
    merged.update(consent or {})
    _require(merged["name"] in NAME_SCOPE, f"姓名公开范围无效：{merged['name']}")
    _require(merged["location"] in LOCATION_GRANULARITY, f"位置公开粒度无效：{merged['location']}")
    _require(merged["image"] in IMAGE_SCOPE, f"影像公开范围无效：{merged['image']}")
    return merged


def normalize_time_range(value, field="event_time_range"):
    """把年份范围规范为 {"start": int, "end": int}；允许整体缺省。"""
    if value is None:
        return None
    _require(isinstance(value, dict), f"{field} 应为包含 start 与 end 的对象")
    start, end = value.get("start"), value.get("end")
    _require(start is not None and end is not None, f"{field} 需要 start 与 end")
    start, end = int(start), int(end)
    _require(start <= end, f"{field} 的起始年份不能晚于结束年份")
    return {"start": start, "end": end}


def normalize_location(location):
    """地点候选至少精确到县区，可另带乡镇与具体地名。"""
    _require(isinstance(location, dict), "地点候选应为对象")
    county = (location.get("county") or "").strip()
    _require(county, "地点候选至少需给出县区")
    result = {"county": county}
    for key in ("township", "name"):
        value = (location.get(key) or "").strip()
        if value:
            result[key] = value
    return result


def new_editor(record_id, name, roles, now=None):
    """编辑账号；roles 取自 EDITOR_ROLES，决定其可做的核验动作。"""
    unknown = sorted(set(roles or []) - set(EDITOR_ROLES))
    _require(not unknown, f"未知编辑权限：{unknown}")
    _require(name and name.strip(), "编辑姓名不能为空")
    return {
        "id": record_id,
        "name": name.strip(),
        "roles": list(roles or []),
        "created_at": now or utcnow(),
    }


def new_narrator(record_id, name, contact, consent=None, now=None):
    """讲述人。contact 仅供编辑部内部联络，任何发布视图都不得携带。"""
    _require(name and name.strip(), "讲述人姓名不能为空")
    return {
        "id": record_id,
        "name": name.strip(),
        "contact": contact or "",
        "consent": validate_consent(consent),
        "consent_withdrawn_at": None,
        "created_at": now or utcnow(),
    }


def new_evidence(record_id, type, title, content="", county=None, date_range=None,
                 source=None, narrator_id=None, now=None):
    """证据：口述片段、影像、公开档案或水文记录。

    口述与影像必须关联讲述人，以便套用其授权范围；档案与水文记录
    应注明公开来源 source。
    """
    _require(type in EVIDENCE_TYPES, f"证据类型无效：{type}")
    _require(title and title.strip(), "证据标题不能为空")
    if type in ("oral", "image"):
        _require(narrator_id, "口述与影像证据必须关联讲述人，以便套用授权范围")
    return {
        "id": record_id,
        "type": type,
        "title": title.strip(),
        "content": content or "",
        "county": (county or "").strip() or None,
        "date_range": normalize_time_range(date_range, "date_range"),
        "source": source,
        "narrator_id": narrator_id,
        "revised_at": None,
        "revisions": [],
        "created_at": now or utcnow(),
    }


def new_statement(record_id, narrator_id, text, event_time_range=None,
                  location_candidates=None, now=None):
    """口述中的具体陈述，携带大致时间范围与旧地名的现址候选。"""
    _require(text and text.strip(), "陈述内容不能为空")
    return {
        "id": record_id,
        "narrator_id": narrator_id,
        "text": text.strip(),
        "event_time_range": normalize_time_range(event_time_range),
        "location_candidates": [normalize_location(loc) for loc in (location_candidates or [])],
        "status": "pending",
        "decisions": [],
        "created_at": now or utcnow(),
    }


def new_citation(record_id, statement_id, evidence_id, relation,
                 confirmed=True, origin="editor", note="", now=None):
    """陈述与证据之间的一条引用。系统建议只能作为未确认线索。"""
    _require(relation in RELATIONS, f"引用关系无效：{relation}")
    _require(origin in ("editor", "system"), f"引用来源无效：{origin}")
    return {
        "id": record_id,
        "statement_id": statement_id,
        "evidence_id": evidence_id,
        "relation": relation,
        "confirmed": bool(confirmed),
        "origin": origin,
        "note": note or "",
        "created_at": now or utcnow(),
    }


def new_feature(record_id, title, statement_ids=None, now=None):
    """专题稿件。versions 保存历次刊发快照，只增不改。"""
    _require(title and title.strip(), "专题标题不能为空")
    return {
        "id": record_id,
        "title": title.strip(),
        "statement_ids": list(statement_ids or []),
        "state": "draft",
        "versions": [],
        "created_at": now or utcnow(),
    }


def new_correction(record_id, feature_id, kind, affected_statement_ids,
                   reason, created_by, now=None):
    """读者可见的更正或撤回记录，只指出受影响的陈述。"""
    _require(kind in CORRECTION_KINDS, f"更正类型无效：{kind}")
    _require(affected_statement_ids, "更正记录需指出受影响的陈述")
    _require(reason and reason.strip(), "更正记录需说明理由")
    return {
        "id": record_id,
        "feature_id": feature_id,
        "kind": kind,
        "affected_statement_ids": list(affected_statement_ids),
        "reason": reason.strip(),
        "created_by": created_by,
        "created_at": now or utcnow(),
    }
