"""自动提示：发现矛盾与相似线索。

本模块只读不写——提示交给编辑参考；成立、存疑、不宜公开
一律由有权限的编辑在 workflow 中决定，本模块不改变任何记录。
"""

from .consent import blocked_statement_ids

_PUNCTUATION = "，。、；：？！“”‘’（）《》…—·「」"


def _ranges_overlap(a, b):
    """任一范围缺失时不构成冲突，按重叠处理。"""
    if not a or not b:
        return True
    return a["start"] <= b["end"] and b["start"] <= a["end"]


def _bigrams(text):
    chars = [ch for ch in text if not ch.isspace() and ch not in _PUNCTUATION]
    return {"".join(chars[i:i + 2]) for i in range(len(chars) - 1)}


def _similarity(left, right):
    """二字元 Jaccard 相似度，适合中文短文本的粗略比对。"""
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _statement_counties(statement):
    return {loc["county"] for loc in statement["location_candidates"]}


def contradictions(store, statement_id):
    """比对陈述与其已确认引用证据的时间、地点，返回矛盾提示列表。"""
    statement = store.get("statements", statement_id)
    found = []
    for citation in store.citations_for_statement(statement_id):
        if not citation["confirmed"]:
            continue
        evidence = store.get("evidence", citation["evidence_id"])
        time_range = statement["event_time_range"]
        date_range = evidence["date_range"]
        if time_range and date_range and not _ranges_overlap(time_range, date_range):
            found.append({
                "kind": "time_conflict",
                "evidence_id": evidence["id"],
                "detail": (
                    f"陈述时间 {time_range['start']}-{time_range['end']} 年"
                    f"与证据《{evidence['title']}》记录 {date_range['start']}-{date_range['end']} 年不重叠"
                ),
            })
        counties = _statement_counties(statement)
        if evidence["county"] and counties and evidence["county"] not in counties:
            found.append({
                "kind": "location_conflict",
                "evidence_id": evidence["id"],
                "detail": (
                    f"证据《{evidence['title']}》记录地为{evidence['county']}，"
                    "不在陈述的地点候选之内"
                ),
            })
    return found


def similar_statements(store, statement_id, threshold=0.25):
    """寻找可能指向同一事件的其他陈述（同县区且时间重叠，或文本相近）。"""
    statement = store.get("statements", statement_id)
    counties = _statement_counties(statement)
    found = []
    for other in store.all("statements"):
        if other["id"] == statement_id:
            continue
        shared = counties & _statement_counties(other)
        similarity = _similarity(statement["text"], other["text"])
        if (shared and _ranges_overlap(statement["event_time_range"], other["event_time_range"])) \
                or similarity >= threshold:
            found.append({
                "statement_id": other["id"],
                "shared_counties": sorted(shared),
                "similarity": round(similarity, 3),
            })
    found.sort(key=lambda item: item["similarity"], reverse=True)
    return found


def suggested_evidence(store, statement_id):
    """按同县区、时间重叠与文本相似，给出可建立引用的证据候选。"""
    statement = store.get("statements", statement_id)
    cited = {c["evidence_id"] for c in store.citations_for_statement(statement_id)}
    counties = _statement_counties(statement)
    found = []
    for evidence in store.all("evidence"):
        if evidence["id"] in cited:
            continue
        if counties and evidence["county"] and evidence["county"] not in counties:
            continue
        if not _ranges_overlap(statement["event_time_range"], evidence["date_range"]):
            continue
        similarity = _similarity(statement["text"], evidence["title"] + evidence["content"])
        found.append({
            "evidence_id": evidence["id"],
            "type": evidence["type"],
            "title": evidence["title"],
            "similarity": round(similarity, 3),
        })
    found.sort(key=lambda item: item["similarity"], reverse=True)
    return found


def review_flags(store, statement_id):
    """证据在最近一次核验决定之后被修订时，提示编辑复核。"""
    statement = store.get("statements", statement_id)
    if not statement["decisions"]:
        return []
    last_decided_at = statement["decisions"][-1]["at"]
    flags = []
    for citation in store.citations_for_statement(statement_id):
        if not citation["confirmed"]:
            continue
        evidence = store.get("evidence", citation["evidence_id"])
        if evidence["revised_at"] and evidence["revised_at"] > last_decided_at:
            flags.append({
                "kind": "evidence_revised",
                "evidence_id": evidence["id"],
                "detail": f"证据《{evidence['title']}》在最近一次核验决定后被修订，建议复核",
            })
    return flags


def statement_hints(store, statement_id):
    """汇总一条陈述的全部自动提示。"""
    store.get("statements", statement_id)
    return {
        "statement_id": statement_id,
        "contradictions": contradictions(store, statement_id),
        "similar_statements": similar_statements(store, statement_id),
        "suggested_evidence": suggested_evidence(store, statement_id),
        "review_flags": review_flags(store, statement_id),
    }


def feature_gaps(store, feature_id):
    """专题的证据缺口：未决、存疑、不宜公开、缺佐证、矛盾未解、授权撤回。"""
    feature = store.get("features", feature_id)
    blocked = set(blocked_statement_ids(store, feature_id))
    gaps = []
    for statement_id in feature["statement_ids"]:
        statement = store.get("statements", statement_id)
        if statement_id in blocked:
            gaps.append({
                "statement_id": statement_id,
                "kind": "consent_withdrawn",
                "detail": "讲述人已撤回授权，材料不得继续使用",
            })
            continue
        status = statement["status"]
        if status == "pending":
            gaps.append({
                "statement_id": statement_id,
                "kind": "undecided",
                "detail": "尚未作出核验决定",
            })
        elif status == "doubtful":
            gaps.append({
                "statement_id": statement_id,
                "kind": "doubtful",
                "detail": "陈述存疑，暂不可刊发",
            })
        elif status == "restricted":
            gaps.append({
                "statement_id": statement_id,
                "kind": "restricted",
                "detail": "陈述不宜公开",
            })
        elif status == "verified":
            supported = any(
                c["confirmed"] and c["relation"] == "support"
                for c in store.citations_for_statement(statement_id)
            )
            if not supported:
                gaps.append({
                    "statement_id": statement_id,
                    "kind": "missing_support",
                    "detail": "缺少已确认的支持性引用",
                })
            if contradictions(store, statement_id):
                gaps.append({
                    "statement_id": statement_id,
                    "kind": "unresolved_conflict",
                    "detail": "存在未解决的矛盾提示",
                })
    return gaps
