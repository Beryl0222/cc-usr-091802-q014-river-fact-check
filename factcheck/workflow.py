"""核验工作流：登记、编辑决定、授权撤回、刊发、更正与证据修订。

所有会改变记录的动作都集中在这一层，并按角色鉴权；
自动提示（hints）不进入本层，也不能代替编辑作结论。
"""

import copy

from . import models, publish
from .consent import blocked_statement_ids, material_statement_ids
from .errors import ConflictError


def _require_role(store, editor_id, role):
    if not editor_id:
        raise PermissionError("缺少编辑身份")
    try:
        editor = store.get("editors", editor_id)
    except KeyError:
        raise PermissionError(f"编辑 {editor_id} 不存在") from None
    if role not in editor["roles"]:
        raise PermissionError(f"编辑 {editor['name']} 缺少 {role} 权限")
    return editor


# ---- 登记 ----

def register_editor(store, name, roles):
    record = models.new_editor(store.next_id("editors"), name, roles)
    store.add("editors", record)
    store.save()
    return record


def register_narrator(store, name, contact, consent=None):
    record = models.new_narrator(store.next_id("narrators"), name, contact, consent)
    store.add("narrators", record)
    store.save()
    return record


def register_evidence(store, type, title, content="", county=None,
                      date_range=None, source=None, narrator_id=None):
    if narrator_id:
        store.get("narrators", narrator_id)
    record = models.new_evidence(
        store.next_id("evidence"), type, title, content=content, county=county,
        date_range=date_range, source=source, narrator_id=narrator_id,
    )
    store.add("evidence", record)
    store.save()
    return record


def register_statement(store, narrator_id, text, event_time_range=None,
                       location_candidates=None):
    store.get("narrators", narrator_id)
    record = models.new_statement(
        store.next_id("statements"), narrator_id, text,
        event_time_range=event_time_range, location_candidates=location_candidates,
    )
    store.add("statements", record)
    store.save()
    return record


def register_feature(store, title, statement_ids=None):
    for statement_id in statement_ids or []:
        store.get("statements", statement_id)
    record = models.new_feature(store.next_id("features"), title, statement_ids)
    store.add("features", record)
    store.save()
    return record


def add_statement_to_feature(store, feature_id, statement_id):
    feature = store.get("features", feature_id)
    store.get("statements", statement_id)
    if statement_id not in feature["statement_ids"]:
        feature["statement_ids"].append(statement_id)
        store.save()
    return feature


def remove_statement_from_feature(store, feature_id, statement_id):
    feature = store.get("features", feature_id)
    if statement_id in feature["statement_ids"]:
        feature["statement_ids"].remove(statement_id)
        store.save()
    return feature


# ---- 引用与核验决定 ----

def add_citation(store, editor_id, statement_id, evidence_id, relation, note=""):
    """编辑把陈述与证据逐一建立引用；系统建议只能作为未确认线索。"""
    _require_role(store, editor_id, "verify")
    store.get("statements", statement_id)
    store.get("evidence", evidence_id)
    record = models.new_citation(
        store.next_id("citations"), statement_id, evidence_id, relation,
        confirmed=True, origin="editor", note=note,
    )
    store.add("citations", record)
    store.save()
    return record


def decide_statement(store, editor_id, statement_id, status, note="", now=None):
    """编辑对陈述作出成立、存疑或不宜公开的结论，并留存决定历史。"""
    _require_role(store, editor_id, "verify")
    if status not in models.DECIDABLE_STATUS:
        raise ValueError(f"核验结论只能是：{', '.join(models.DECIDABLE_STATUS)}")
    statement = store.get("statements", statement_id)
    statement["decisions"].append({
        "by": editor_id,
        "at": now or models.utcnow(),
        "status": status,
        "note": note or "",
    })
    statement["status"] = status
    store.save()
    return statement


# ---- 授权与撤回 ----

def update_consent(store, narrator_id, consent):
    """登记讲述人对姓名、精确位置、影像公开范围的调整。

    新范围立即作用于未刊发的视图；已刊发版本保留当时依据。
    """
    narrator = store.get("narrators", narrator_id)
    narrator["consent"] = models.validate_consent(consent)
    store.save()
    return narrator


def withdraw_consent(store, narrator_id, now=None):
    """撤回授权：未刊发稿件停用材料；已刊发稿件生成读者可见撤回记录。"""
    narrator = store.get("narrators", narrator_id)
    timestamp = now or models.utcnow()
    narrator["consent_withdrawn_at"] = timestamp
    retractions = []
    for feature in store.all("features"):
        if feature["state"] != "published":
            continue
        affected = material_statement_ids(store, feature["id"], narrator_id)
        if not affected:
            continue
        record = models.new_correction(
            store.next_id("corrections"), feature["id"], "retraction",
            affected, "讲述人撤回授权，相关材料停止再版使用", "system",
            now=timestamp,
        )
        store.add("corrections", record)
        retractions.append(record)
    store.save()
    return {
        "narrator_id": narrator_id,
        "withdrawn_at": timestamp,
        "retractions": retractions,
    }


# ---- 刊发与更正 ----

def publish_feature(store, editor_id, feature_id, now=None):
    """刊发专题：生成不可改写的版本快照（含当时的核验与授权依据）。"""
    _require_role(store, editor_id, "publish")
    feature = store.get("features", feature_id)
    blocked = blocked_statement_ids(store, feature_id)
    if blocked:
        raise ConflictError(
            f"陈述 {', '.join(blocked)} 的讲述人已撤回授权，请从稿件中移除后再刊发"
        )
    items = publish.timeline_items(store, feature_id)
    if not items:
        raise ConflictError("稿件内没有可刊发的成立陈述")
    basis = {}
    for statement_id in feature["statement_ids"]:
        statement = store.get("statements", statement_id)
        narrator = store.get("narrators", statement["narrator_id"])
        basis[statement_id] = {
            "status": statement["status"],
            "consent": dict(narrator["consent"]),
        }
    version = {
        "version": len(feature["versions"]) + 1,
        "published_at": now or models.utcnow(),
        "published_by": editor_id,
        "items": copy.deepcopy(items),
        "basis": basis,
    }
    feature["versions"].append(version)
    feature["state"] = "published"
    store.save()
    return version


def add_correction(store, editor_id, feature_id, statement_ids, reason,
                   kind="correction", now=None):
    """对已刊发专题追加读者可见的更正/撤回记录，只指出受影响的陈述。"""
    _require_role(store, editor_id, "verify")
    feature = store.get("features", feature_id)
    if feature["state"] != "published":
        raise ConflictError("仅已刊发专题需要更正记录")
    unknown = sorted(set(statement_ids) - set(feature["statement_ids"]))
    if unknown:
        raise ValueError(f"陈述不属于该专题：{', '.join(unknown)}")
    record = models.new_correction(
        store.next_id("corrections"), feature_id, kind,
        sorted(set(statement_ids)), reason, editor_id, now=now,
    )
    store.add("corrections", record)
    store.save()
    return record


def revise_evidence(store, editor_id, evidence_id, updates, reason, now=None):
    """修订证据：保留修订历史，并向采用它的已刊发专题指出受影响陈述。

    同一证据被多个专题采用时，每个专题各收到一条更正记录，
    只列出本专题内受影响的陈述；已刊发版本快照不被改写。
    """
    _require_role(store, editor_id, "verify")
    evidence = store.get("evidence", evidence_id)
    allowed = {"title", "content", "county", "source", "date_range"}
    unknown = sorted(set(updates) - allowed)
    if unknown:
        raise ValueError(f"不可修订的字段：{unknown}")
    timestamp = now or models.utcnow()
    before = {}
    for key, value in updates.items():
        if key == "date_range":
            value = models.normalize_time_range(value, "date_range")
        before[key] = evidence.get(key)
        evidence[key] = value
    evidence["revised_at"] = timestamp
    evidence["revisions"].append({
        "at": timestamp,
        "by": editor_id,
        "reason": reason or "",
        "before": before,
    })
    affected = sorted({
        c["statement_id"] for c in store.all("citations")
        if c["evidence_id"] == evidence_id and c["confirmed"]
    })
    notified = []
    for feature in store.all("features"):
        if feature["state"] != "published":
            continue
        hit = [sid for sid in affected if sid in feature["statement_ids"]]
        if not hit:
            continue
        record = models.new_correction(
            store.next_id("corrections"), feature["id"], "correction", hit,
            f"证据《{evidence['title']}》已修订：{reason or '内容更新'}",
            editor_id, now=timestamp,
        )
        store.add("corrections", record)
        notified.append(feature["id"])
    store.save()
    return {
        "evidence_id": evidence_id,
        "affected_statement_ids": affected,
        "features_notified": notified,
    }
