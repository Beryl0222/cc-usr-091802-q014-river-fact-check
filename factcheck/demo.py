"""虚构演示数据集：供测试与本地试用，人物与联系方式均为虚构。"""

from . import workflow
from .store import Store


def build_demo_store():
    """构造一份覆盖主要业务路径的虚构数据。

    返回 (store, 关键记录 id 字典)，便于测试与演示直接引用。
    """
    store = Store()

    verifier = workflow.register_editor(store, "王核验", ["verify", "publish"])
    workflow.register_editor(store, "李记者", [])

    narrator_a = workflow.register_narrator(
        store, "张守河", "internal-contact-001",
        consent={"name": "anonymous", "location": "county", "image": "none"},
    )
    narrator_b = workflow.register_narrator(
        store, "刘渡工", "internal-contact-002",
        consent={"name": "public", "location": "township", "image": "public"},
    )

    hydrology = workflow.register_evidence(
        store, "hydrology", "花园口水文站1958年洪水记录",
        content="1958年7月花园口站出现洪峰。",
        county="惠济区", date_range={"start": 1958, "end": 1958},
        source="公开水文年鉴",
    )
    archive = workflow.register_evidence(
        store, "archive", "县志·1964年水患条目",
        content="1964年夏县境河水漫溢。",
        county="中牟县", date_range={"start": 1964, "end": 1964},
        source="县志数字化公开版",
    )
    image = workflow.register_evidence(
        store, "image", "渡口老照片（1960年代）",
        content="渡口木船与堤岸合影。",
        county="中牟县", date_range={"start": 1960, "end": 1969},
        narrator_id=narrator_b["id"],
    )

    statement_a = workflow.register_statement(
        store, narrator_a["id"],
        "1958年秋天，村北的堤决了口，水漫到打谷场。",
        event_time_range={"start": 1958, "end": 1959},
        location_candidates=[
            {"county": "惠济区", "township": "花园口镇", "name": "石桥村"},
        ],
    )
    statement_b = workflow.register_statement(
        store, narrator_b["id"],
        "1964年发大水，渡口停摆了一个多月。",
        event_time_range={"start": 1964, "end": 1964},
        location_candidates=[
            {"county": "中牟县", "township": "渡口镇"},
        ],
    )

    feature = workflow.register_feature(
        store, "花园口记忆", [statement_a["id"], statement_b["id"]]
    )

    ids = {
        "verifier": verifier["id"],
        "narrator_a": narrator_a["id"],
        "narrator_b": narrator_b["id"],
        "hydrology": hydrology["id"],
        "archive": archive["id"],
        "image": image["id"],
        "statement_a": statement_a["id"],
        "statement_b": statement_b["id"],
        "feature": feature["id"],
    }
    return store, ids
