"""记录仓库：内存索引加可选的 JSON 文件持久化。"""

import json
from pathlib import Path

COLLECTIONS = (
    "narrators",
    "evidence",
    "statements",
    "citations",
    "features",
    "editors",
    "corrections",
)

ID_PREFIX = {
    "narrators": "n",
    "evidence": "ev",
    "statements": "st",
    "citations": "ci",
    "features": "ft",
    "editors": "ed",
    "corrections": "cr",
}


class Store:
    """按集合存放记录的轻量仓库。

    path 为空时为纯内存仓库（测试用）；否则在 save 时整体写回 JSON。
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.data = {name: {} for name in COLLECTIONS}
        self.counters = {name: 0 for name in COLLECTIONS}
        if self.path and self.path.exists():
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            for name in COLLECTIONS:
                self.data[name] = payload.get("data", {}).get(name, {})
                self.counters[name] = payload.get("counters", {}).get(name, 0)

    def next_id(self, collection):
        """生成集合内不重复的短 id。"""
        while True:
            self.counters[collection] += 1
            record_id = f"{ID_PREFIX[collection]}-{self.counters[collection]:04d}"
            if record_id not in self.data[collection]:
                return record_id

    def add(self, collection, record):
        self.data[collection][record["id"]] = record
        return record

    def get(self, collection, record_id):
        try:
            return self.data[collection][record_id]
        except KeyError:
            raise KeyError(f"{collection} 中不存在记录 {record_id}") from None

    def all(self, collection):
        return list(self.data[collection].values())

    # 常用关联查询
    def citations_for_statement(self, statement_id):
        return [c for c in self.all("citations") if c["statement_id"] == statement_id]

    def statements_of_narrator(self, narrator_id):
        return [s for s in self.all("statements") if s["narrator_id"] == narrator_id]

    def corrections_for_feature(self, feature_id):
        records = [c for c in self.all("corrections") if c["feature_id"] == feature_id]
        return sorted(records, key=lambda c: (c["created_at"], c["id"]))

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"counters": self.counters, "data": self.data}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
