"""讲述人授权：公开范围、撤回与材料停用计算。

授权语义：
- 讲述人可分别限定姓名、精确位置、影像的公开范围（见 models.validate_consent）；
- 撤回授权后，尚未刊发的稿件不得继续使用其材料（本人陈述，以及
  引用了其口述或影像证据的他人陈述）；
- 已刊发内容保留当时依据，由 workflow 另行生成读者可见的撤回记录。
"""


def is_withdrawn(narrator):
    return bool(narrator.get("consent_withdrawn_at"))


def material_statement_ids(store, feature_id, narrator_id):
    """专题内用到该讲述人材料的陈述 id 列表。

    “材料”包括讲述人本人的陈述，以及其他陈述中对其口述、
    影像证据建立的引用。
    """
    feature = store.get("features", feature_id)
    own_statements = {s["id"] for s in store.statements_of_narrator(narrator_id)}
    own_evidence = {e["id"] for e in store.all("evidence") if e["narrator_id"] == narrator_id}
    affected = set()
    for statement_id in feature["statement_ids"]:
        if statement_id in own_statements:
            affected.add(statement_id)
            continue
        for citation in store.citations_for_statement(statement_id):
            if citation["evidence_id"] in own_evidence:
                affected.add(statement_id)
                break
    return sorted(affected)


def blocked_statement_ids(store, feature_id):
    """因讲述人撤回授权而不得继续使用的陈述 id 列表。"""
    blocked = set()
    for narrator in store.all("narrators"):
        if is_withdrawn(narrator):
            blocked.update(material_statement_ids(store, feature_id, narrator["id"]))
    return sorted(blocked)
