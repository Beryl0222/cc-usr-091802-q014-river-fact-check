# 黄河叙事事实核验

用于整理沿黄口述、影像、公开档案与水文资料之间的事实引用关系，在融合报道稿件形成前完成事实核验。

## 模块边界

- 编辑把口述中的具体陈述与图片片段、地点候选、时间范围、公开档案、水文记录**逐一建立引用**；
- 自动能力（`factcheck/hints.py`）**只提示矛盾与相似线索**，不改变任何核验状态；
- **成立 / 存疑 / 不宜公开**只能由 `editor` 角色的编辑决定，并留痕可审计；
- 讲述人可分别限定**姓名、精确位置、影像**的公开范围，并可整体或逐项撤回授权；
- 撤回授权：未发布稿件立即停用素材；已刊发内容**保留当时版本**，并生成读者可见的撤回记录；
- 同一证据被多个专题采用时，修订只生成**指向受影响陈述**的更正记录，不重写历史版本；
- 编辑制作时间轴 / 地图稿使用的是脱敏后的可发布视图（叙事、证据缺口、引用来源）；
- 读者能看到更正了什么，但任何视图都不包含讲述人联系方式。

## 结构

- `factcheck/models.py`：领域模型（陈述、引用、提示、授权、版本、更正）
- `factcheck/hints.py`：自动提示（矛盾 / 相似线索 / 旧地名未匹配现址）
- `factcheck/core.py`：引用、决定、授权撤回、发布快照、更正记录的核心逻辑
- `service.py`：HTTP 接口（`/health` 与 `/api/...`）
- `fixtures/`：可公开样例（地名映射等），不含真实个人资料或业务凭据

## 公开范围

| 范围 | 级别 |
| --- | --- |
| 姓名 `name` | `public` 公开 / `pseudonym` 化名 / `internal` 不公开 |
| 位置 `location` | `precise` 精确 / `county` 县级 / `internal` 不公开 |
| 影像 `image` | `public` 公开 / `internal` 不公开 |

默认全部 `internal`，由讲述人逐项授予；撤回（含整体撤回 `all`）立即生效。

## 稿件发布规则

- 存在未核验陈述或已撤回授权的素材时，稿件不可刊发；
- 刊发生成只读的脱敏快照版本，历史版本只增不改；
- 待核验 / 不宜公开 / 已撤回授权的陈述进入「证据缺口」，不进入可发布叙事。

## 运行

```bash
python3 service.py --check                 # 基础检查
python3 service.py --port 8000             # 启动服务
python3 -m unittest discover -s tests -v   # 契约与行为测试
```

## HTTP 接口

变更类接口在请求体中携带 `actor: {"id": ..., "role": "editor"}` 表示操作人；
只有 `editor` 角色可以作出核验决定、刊发稿件、修订证据。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 服务身份 |
| POST | `/api/narrators` | 登记讲述人（响应不含联系方式） |
| POST | `/api/narrators/{id}/consent` | 设定某项公开范围级别 |
| POST | `/api/narrators/{id}/withdraw` | 撤回授权（`scope` 缺省为 `all`） |
| POST | `/api/materials` | 登记素材（口述 / 影像 / 档案 / 水文） |
| POST | `/api/materials/{id}/revisions` | 修订证据，生成受影响陈述的更正记录 |
| POST | `/api/claims` | 登记陈述，自动给出地点候选与提示 |
| GET | `/api/claims/{id}` | 查看陈述、引用、提示与决定留痕 |
| POST | `/api/claims/{id}/citations` | 建立陈述到素材（可到片段）的引用 |
| POST | `/api/claims/{id}/decision` | 编辑决定：成立 / 存疑 / 不宜公开 |
| POST | `/api/stories` | 组建专题稿件 |
| GET | `/api/stories/{id}/publishable` | 脱敏可发布视图（叙事 + 缺口 + 来源） |
| POST | `/api/stories/{id}/publish` | 刊发，生成只读版本快照 |
| GET | `/api/stories/{id}/corrections` | 读者可见的更正 / 撤回记录 |

错误映射：参数不合法 `400`、无权限 `403`、对象不存在 `404`。
