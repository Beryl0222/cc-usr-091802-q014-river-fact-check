"""仓库的 JSON 持久化与装载。"""

import tempfile
import unittest
from pathlib import Path

from factcheck import workflow
from factcheck.store import Store


class PersistenceTest(unittest.TestCase):
    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            store = Store(path)
            editor = workflow.register_editor(store, "王核验", ["verify"])
            narrator = workflow.register_narrator(store, "张守河", "internal-contact-001")
            statement = workflow.register_statement(
                store, narrator["id"], "1958年秋天，村北的堤决了口。",
                event_time_range={"start": 1958, "end": 1959},
                location_candidates=[{"county": "惠济区"}],
            )
            workflow.decide_statement(store, editor["id"], statement["id"], "verified")

            loaded = Store(path)
            restored = loaded.get("statements", statement["id"])
            self.assertEqual(restored["status"], "verified")
            self.assertEqual(restored["event_time_range"], {"start": 1958, "end": 1959})
            # id 计数器随仓库恢复，不会与既有记录冲突
            follow_up = workflow.register_narrator(loaded, "刘渡工", "internal-contact-002")
            self.assertNotEqual(follow_up["id"], narrator["id"])

    def test_in_memory_store_needs_no_path(self):
        store = Store()
        store.save()  # 无路径时为 no-op
        self.assertEqual(store.all("narrators"), [])


if __name__ == "__main__":
    unittest.main()
