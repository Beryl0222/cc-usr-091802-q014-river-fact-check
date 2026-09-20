"""黄河叙事事实核验模块。

把口述中的具体陈述与图片片段、地点候选、时间范围、公开档案和
水文记录逐一建立引用；自动能力只提示矛盾与相似线索，成立、存疑、
不宜公开由有权限的编辑决定；讲述人的授权与撤回贯穿刊发全流程。
"""

from . import consent, hints, models, publish, workflow
from .errors import ConflictError
from .store import Store

__all__ = [
    "consent",
    "hints",
    "models",
    "publish",
    "workflow",
    "ConflictError",
    "Store",
]
