"""自动提示模块。

只负责发现矛盾与相似线索并生成提示，永不改变陈述的核验状态；
成立、存疑、不宜公开只能由有权限的编辑决定。
"""

from __future__ import annotations

import difflib

from .models import EVENT_LABELS, Hint, HintKind, MaterialType

FUZZY_THRESHOLD = 0.6


def location_candidates(place_name, gazetteer):
    """把口述中的（旧）地名映射到现址候选，按匹配度降序。"""
    place_name = (place_name or "").strip()
    if not place_name:
        return []
    found = {}
    for entry in gazetteer:
        old, current, county = entry["old"], entry["current"], entry["county"]
        if place_name in (old, current):
            score = 1.0
        elif place_name in current or place_name in old:
            score = 0.85
        else:
            score = max(
                difflib.SequenceMatcher(None, place_name, old).ratio(),
                difflib.SequenceMatcher(None, place_name, current).ratio(),
            )
        if score >= FUZZY_THRESHOLD:
            found[current] = {
                "name": current,
                "county": county,
                "matched": old,
                "score": round(score, 2),
            }
    return sorted(found.values(), key=lambda c: -c["score"])


def collect(claim, all_claims, all_materials):
    """汇总一条陈述的全部自动提示。"""
    hints = []
    if not claim.location_candidates:
        hints.append(
            Hint(
                id="",
                claim_id=claim.id,
                kind=HintKind.PLACE_UNRESOLVED,
                message=f"旧地名「{claim.place_name}」未匹配到现址，请人工核对地点候选",
            )
        )
    hints.extend(_record_hints(claim, all_materials))
    hints.extend(_similar_claim_hints(claim, all_claims))
    hints.extend(_image_hints(claim, all_materials))
    return hints


def _years_overlap(a0, a1, b0, b1):
    return a0 <= b1 and b0 <= a1


def _material_place_matches(claim, material):
    place = (material.place or "").strip()
    if not place:
        return False
    if place == claim.place_name:
        return True
    return any(
        place in cand["name"] or place in cand["county"] or place == cand.get("matched")
        for cand in claim.location_candidates
    )


def _record_hints(claim, materials):
    """对照水文与公开档案：时段内的同类记录是相似线索，时段外的是矛盾。"""
    if not claim.event:
        return []
    hints = []
    label = EVENT_LABELS.get(claim.event, claim.event)
    for m in materials:
        if m.type not in (MaterialType.HYDROLOGY, MaterialType.ARCHIVE):
            continue
        if not _material_place_matches(claim, m):
            continue
        years = sorted(
            r["year"] for r in m.records if r.get("event") == claim.event and r.get("year")
        )
        if not years:
            continue
        inside = [y for y in years if claim.year_start <= y <= claim.year_end]
        if inside:
            hints.append(
                Hint(
                    id="",
                    claim_id=claim.id,
                    kind=HintKind.SIMILAR,
                    message=(
                        f"《{m.title}》在口述时段内记录有{label}"
                        f"（{'、'.join(map(str, inside))}年），可作为佐证线索"
                    ),
                    refs=[m.id],
                )
            )
        else:
            hints.append(
                Hint(
                    id="",
                    claim_id=claim.id,
                    kind=HintKind.CONTRADICTION,
                    message=(
                        f"口述称{claim.year_start}–{claim.year_end}年发生{label}，"
                        f"但《{m.title}》的记录年份为{'、'.join(map(str, years))}，存在矛盾"
                    ),
                    refs=[m.id],
                )
            )
    return hints


def _similar_claim_hints(claim, all_claims):
    """其他讲述人在同时段、同区域的陈述，作为交叉印证线索。"""
    hints = []
    counties = {c["county"] for c in claim.location_candidates}
    for other in all_claims:
        if other.id == claim.id or other.narrator_id == claim.narrator_id:
            continue
        if not _years_overlap(claim.year_start, claim.year_end, other.year_start, other.year_end):
            continue
        other_counties = {c["county"] for c in other.location_candidates}
        if counties or other_counties:
            if not (counties and other_counties and counties & other_counties):
                continue
        elif other.place_name != claim.place_name:
            continue
        hints.append(
            Hint(
                id="",
                claim_id=claim.id,
                kind=HintKind.SIMILAR,
                message=f"另有陈述（{other.id}）提及同时段同区域事件，可交叉印证",
                refs=[other.id],
            )
        )
    return hints


def _image_hints(claim, materials):
    """时段与地点相近的影像素材及其片段，作为可参考的相似线索。"""
    hints = []
    for m in materials:
        if m.type != MaterialType.IMAGE or m.year_start is None:
            continue
        if not _years_overlap(claim.year_start, claim.year_end, m.year_start, m.year_end or m.year_start):
            continue
        if not _material_place_matches(claim, m):
            continue
        frag_ids = [f.get("id") for f in m.fragments if f.get("id")]
        message = f"影像素材《{m.title}》的时段与地点相近"
        if frag_ids:
            message += f"，可参考片段：{'、'.join(frag_ids)}"
        hints.append(
            Hint(id="", claim_id=claim.id, kind=HintKind.SIMILAR, message=message, refs=[m.id] + frag_ids)
        )
    return hints
