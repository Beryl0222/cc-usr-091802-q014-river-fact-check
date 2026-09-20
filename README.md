# 黄河叙事事实核验

用于整理沿黄口述、影像、公开档案与水文资料之间的事实引用关系。

`fixtures/sample.json` 保存可公开的领域样例，只用于说明数据边界，不包含真实个人资料或业务凭据。

执行 `python3 service.py --check` 可检查项目身份，运行 `python3 -m unittest discover -s tests -v` 可核对基础契约。服务启动后，`/health` 返回项目标识。

## 核验模块

`factcheck/` 是稿件形成前的事实核验模块，围绕五类记录工作：

- **陈述（statement）**：口述中的具体陈述，携带大致时间范围与旧地名的现址候选；
- **证据（evidence）**：口述片段、影像、公开档案、水文记录，档案与水文需注明公开来源；
- **引用（citation）**：编辑把陈述与证据逐一建立的关联（支持 / 矛盾 / 背景）；
- **专题（feature）**：稿件，刊发时生成不可改写的版本快照（含当时的核验与授权依据）；
- **更正（correction）**：读者可见的更正或撤回记录，只指出受影响的陈述。

### 自动能力的边界

`factcheck/hints.py` 只读不写，负责提示：时间或地点矛盾、相似陈述、可引用的证据候选、决定后证据被修订的复核提示，以及专题的证据缺口。**成立、存疑、不宜公开**只能由具备 `verify` 权限的编辑通过 `workflow.decide_statement` 决定；刊发需 `publish` 权限。

### 授权、撤回与脱敏

- 讲述人可分别限定姓名（匿名 / 公开）、精确位置（县区 / 乡镇 / 村落）、影像（不公开 / 公开）的公开范围，默认取最严格口径；
- 撤回授权后，未刊发稿件不得继续使用其材料（含被他人陈述引用的口述、影像），刊发动作会被拒绝；
- 已刊发内容保留当时依据（版本快照不改写），并自动生成读者可见的撤回记录；
- 编辑制作时间轴或地图稿时，拿到的是脱敏后的可发布叙事、证据缺口与引用来源；读者能看到更正了什么，但任何视图都不携带讲述人联系方式。

### 证据修订

同一证据被多个专题采用时，`workflow.revise_evidence` 保留修订历史，并向每个已刊发专题各追加一条更正记录，只列出本专题内受影响的陈述；历史版本不被重写。

## HTTP API

`python3 service.py --port 8000 --data data/store.json` 启动服务。需要编辑身份的接口通过请求头 `X-Editor-Id` 识别（本服务不含登录体系，部署时应置于内网或网关之后）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 服务标识 |
| POST | `/api/editors` | 登记编辑（`roles` 取 `verify`、`publish`） |
| POST | `/api/narrators` | 登记讲述人及授权范围 |
| POST | `/api/narrators/{id}/consent` | 调整授权范围 |
| POST | `/api/narrators/{id}/withdraw` | 撤回授权 |
| POST | `/api/evidence` | 登记证据 |
| POST | `/api/evidence/{id}/revise` | 修订证据（需 `verify`） |
| POST | `/api/statements` | 登记陈述 |
| POST | `/api/statements/{id}/citations` | 建立引用（需 `verify`） |
| POST | `/api/statements/{id}/decision` | 核验决定（需 `verify`） |
| GET | `/api/statements/{id}/hints` | 自动提示（矛盾、相似、候选证据） |
| POST | `/api/features` | 建立专题 |
| POST | `/api/features/{id}/statements` | 稿件加入陈述 |
| POST | `/api/features/{id}/statements/remove` | 稿件移除陈述 |
| POST | `/api/features/{id}/publish` | 刊发（需 `publish`），生成版本快照 |
| GET | `/api/features/{id}/timeline` | 脱敏时间轴视图（含证据缺口） |
| GET | `/api/features/{id}/map` | 脱敏地图视图（按地点归并） |
| GET | `/api/features/{id}/gaps` | 证据缺口 |
| POST | `/api/features/{id}/corrections` | 追加更正记录（需 `verify`） |
| GET | `/api/features/{id}/corrections` | 读者可见的更正记录 |
| GET | `/api/features/{id}/published` | 读者视图（最新刊发版本 + 更正记录） |

示例：

```bash
curl -X POST localhost:8000/api/statements/st-0001/decision \
  -H 'X-Editor-Id: ed-0001' -H 'Content-Type: application/json' \
  -d '{"status": "verified", "note": "已比对水文记录"}'
curl localhost:8000/api/features/ft-0001/timeline
```

`factcheck.demo.build_demo_store()` 提供一份虚构演示数据（人物与联系方式均为虚构），可用于本地试用与测试。
