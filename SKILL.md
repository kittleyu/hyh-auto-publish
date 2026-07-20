---
name: hyh-auto-publish
description: |
  360智见 GEO（huiyouhua.com）运营后台「创作发布管理」自动发文技能。
  拉取指定公司最新「审核完成且待发布」的 AI 文章，从用户历史媒体里按主题相关性
  挑选信源，生成「文章→媒体」映射表，经人工确认后直接调用后台 dispatch 接口批量发布，
  最后核对真实发布状态。

  触发词：自动发布、GEO 发布、信源选择、创作发布管理、发文、huiyouhua 发布
---

# hyh-auto-publish — 360智见 GEO 自动发文

> 状态：**端到端已跑通**（审核 → 生成映射 → 人工确认 → dispatch 批量发布 → 核对状态）。
> 入口：`https://yunying.huiyouhua.com/cms-yunying.html?tab=articles`（AI创作 → 创作发布管理）
> 登录账号：`HYH_USER` / `HYH_PWD`（与运营后台同一账号）

## 业务目标

把指定公司最新 N 篇「审核完成且待发布」的 AI 文章，按「最易被 AI 搜索抓取 + 主题相关」的信源批量发布，提升 GEO 可见性。

## ⚠️ 用户偏好（长期有效，务必遵守）

1. **媒体默认从「历史记录」里挑**：后台「创作发布管理 → 选择媒体」按钮**右侧有「历史记录」面板**，里面是用户以前发布过的媒体。对应脚本参数 `--candidate-source history`（**已是默认值**）。不要再退回全平台热度乱选。
2. **优先选与文章主题相关的媒体平台**：如医院/医疗类 → 医疗健康历史媒体；期货公司 → 雪球/东方财富/新浪财经/知乎/百家号等金融财经历史媒体；游戏类 → 游戏媒体。**避免选与主题不相关的行业媒体**（曾用「选车网/汽车之家」发二次元游戏文被用户否决）。
3. **选定媒体后必须先跟用户确认再真实发布**（用户原话："找好发布媒体后需要跟我确认再发"）。发布动作不可逆，仍须确认。
4. **智豆不限量**：用户 2026-07-20 明确「智豆是不限制的」——之前 dispatch 报「账户余额不足」并非真实额度限制（疑为瞬时异常）。因此选媒体时**不必为省钱牺牲主题相关性/权威性**，优先选最相关、最权威的历史媒体即可。

## 已确认的关键事实

| 项 | 结论 |
|----|------|
| 真实入口 | `https://yunying.huiyouhua.com/cms-yunying.html?tab=articles`（AI创作 → 创作发布管理）。早期 `?tab=publishDashboard` 只是只读看板，无发布按钮 |
| 登录账号 | 与运营后台同一账号 `HYH_USER` / `HYH_PWD` |
| 当前默认公司 | 账号活跃公司（如 3049=贵阳脉通血管医院）。可用 `CORP_ID` 环境变量切换任意可达公司 |
| 可发文章状态 | `audit_status=1`（审核完成）且 `publish_status=0`（待发布） |
| 审核状态枚举 `Ju` | `Pending=-1`（待审核）、`Approved=1`（审核完成）、`Rejected=2`（已拒绝）。⚠️ **待审核是 -1，不是 0** |
| 发布状态枚举 `Yu` | `0未发布 / 1待发布 / 2发布中 / 3已发布 / 4失败 / 5排队中`。发布成功后字段变 3（刚发可能短暂为 2，稍后转 3） |
| 发布 API | `POST /yunying/v1/articles/media/{media_id}/dispatch` Body `{"article_ids":[id1,id2,...]}` → `派发成功` |
| 媒体热度指标 | `media.quote_cnt` = 平台内置「AI 引用次数」。⚠️ **实测基本是坏的**：corp 4104 的 100 个自媒体仅 2 个 >0（都是「有驾」=0.02，单价却最贵 10864）。按 quote_cnt 排序会退化成「选最贵媒体」，**成本优先用 `--sort price`** |
| 媒体列表 `/media` | 含 `quote_cnt`；字段 `id/name/platform.platform_name` |
| 发文历史 `media-history` | 用户历史用过的媒体；**不含 quote_cnt**，且 `media_id` 与 `/media` 的 `id` **不是同一套 ID**（无法反查热度） |
| 过滤参数被忽略 | `publish_status` 与 `order_id` 过滤参数**后端直接忽略**，实际返回全量。要精确锁定需在客户端按 id 过滤，或读每篇 `publish_status` 字段判断 |
| 历史媒体会被禁用 | 部分历史媒体已被平台停用，派发返回 **"媒体ID 已被禁用"**。选媒体不能假设历史媒体都可用；多发前先小批量试或接受失败重试 |

## 核心接口

| 用途 | 接口 | 说明 |
|------|------|------|
| 当前用户 | `GET /yunying/v1/user/current?platform=win` | 含 `corp_id` / `corp_name` |
| 切换公司 | `GET /yunying/v1/auth/changecorp?corp_id=X` | 设 `CORP_ID` 后脚本自动切换 |
| 可发文章 | `GET /yunying/v1/creation/articles?page=1&page_size=N&audit_status=1&publish_status=0` | ⚠️ `publish_status`/`order_id` 被忽略，返回全量已审核文章。精确锁定用 `--ids` 或读每篇 `publish_status` |
| 审核通过 | `POST /yunying/v1/article/{article_id}/update` Body `{"id":<id>,"audit_status":1}` | 待审核(-1)→审核完成(1)。**不扣智豆**。返回 `{"code":0,"message":"操作成功"}`。注意用 **POST**（PUT 返回 404） |
| 词包 | `GET /yunying/v1/keyword/package?page=1&page_size=10000` | 含 `distilled_keywords` / `core_keyword` |
| 媒体列表 | `GET /yunying/v1/media?media_type=2&sort_by=quote_cnt&sort_order=desc` | `media_type=1` 新闻，`2` 自媒体；含 `quote_cnt` |
| 发文历史 | `GET /yunying/v1/articles/media-history?page=1&page_size=1000` | 历史媒体候选池（history 模式用）；字段 `media_id/media_name/platform_name/price` |
| 发布 | `POST /yunying/v1/articles/media/{media_id}/dispatch` | Body `{"article_ids":[...]}` → `派发成功` |
| 发布进度 | `GET /yunying/v1/articles/publish-articles?page=1&page_size=N` | 发文进度管理列表，`data.templates[]`，含 `status`/`media_id`/`media_name`/`platform_name` |

## 文章 / 媒体字段

**文章（creation/articles）**
```json
{ "id": 247059, "title": "...", "keyword_package_id": 5539,
  "keywords": ["贵阳静脉曲张医院推荐", ...], "audit_status": 1, "publish_status": 0 }
```

**媒体（/media）** —— 含热度 `quote_cnt`
```json
{ "id": 396388, "name": "信息速报", "platform": {"platform_name": "搜狐"},
  "price": 1164, "quote_cnt": 0, "media_type": 2 }
```

**媒体（media-history）** —— 字段名不同、无 quote_cnt
```json
{ "id": 125513, "media_id": 26212, "media_name": "中国网蓝田（知乎官方认证）",
  "media_type": 1, "platform_name": "中国网", "region": "全国", "price": 2000 }
```
> ⚠️ 两数据源字段不统一：`/media` 用 `id/name/platform.platform_name`；`media-history` 用 `media_id/media_name/platform_name`。
> `build_map.py` 用 `normalize_candidate()` 统一为 `{id, name, platform_name, price, quote_cnt, media_type, region}`。
> history 模式只能按价格排序（无热度）；要按热度发布用默认 `all` 模式（来自 /media）。

## 自动化流程

```
0.（若文章是「待审核」）audit_run.py 批量审核通过（不扣豆）
1. build_map.py 拉取最新 N 篇 audit_status=1 & publish_status=0 文章
2. 读取词包 distilled_keywords（仅用于映射表展示）
3. 拉取候选媒体池（默认 history：GET /articles/media-history）
4. 按主题相关性/价格筛选媒体（--media-ids 白名单可精确指定并保序）
5. 文章在选定媒体间轮转分配（--top-k，分散到多平台利于 AI 抓取）
6. 生成 article→media 映射表 JSON
7. ★ 暂停，把映射表交给用户确认（媒体选择 + 成本）
8. 确认后 publish_run.py 调用 POST /articles/media/{media_id}/dispatch（按 media 分组批量派发）
9. verify_publish.py 读真实 publish_status 核对（应全为 3=已发布；禁用媒体失败则换备用媒体重试）
```

## 脚本清单

| 脚本 | 用途 |
|------|------|
| `build_map.py` | 登录 → 拉文章/词包/媒体 → 归一化 → 生成映射表。参数：`--ids "id1,id2"`（只对指定文章）、`--media-ids "id1,id2"`（媒体白名单，指定历史媒体并保序）、`--sort price\|quote_cnt`、`--candidate-source all\|history`、`--top-k N`、`--media-type 1\|2`、`--out`、`CORP_ID` 环境变量 |
| `audit_run.py` | 批量审核：拉 `audit_status=-1` 待审核文章，逐篇 POST `/article/{id}/update` 置为审核完成。参数：`--limit N --status 1 --dry-run --out` |
| `publish_run.py` | 读取映射表 → 按 media 分组 → 调用 dispatch 发布。参数：`--map --out --dry-run`（**无 --dry-run 才真实扣豆**） |
| `verify_publish.py` | 核对指定文章真实 `publish_status`（不靠被忽略的过滤参数，逐页匹配读字段）。环境变量 `CORP_ID` / `IDS` |
| `media_probe.py` | 探查候选媒体池的 quote_cnt / price 分布（判断热度数据可用性、找便宜/相关媒体） |
| `inspect_history.py` | 查看某 corp 的发文历史媒体清单（确认有哪些可用历史媒体） |
| `test_dispatch_api.py` | 单篇发布接口连通性测试 |
| `companies.txt` | corp_id ↔ 公司名对照表（含默认公司、重复名公司的多个 corp_id） |

## 用法

```bash
# 运行环境：playwright 装在托管 venv，必须用这个 python（系统 python 无 playwright）
PY="<你的 WorkBuddy 托管 Python venv>/Scripts/python.exe"   # 例: C:/Users/<你>/.workbuddy/binaries/python/envs/default/Scripts/python.exe
SKILL="<本 skill 所在目录>"
cd "$SKILL"
set HYH_USER=<你的后台账号>
set HYH_PWD=<你的后台密码>

# 0.（若文章是「待审核」）先批量审核通过（不扣豆）
CORP_ID=<ID> $PY audit_run.py --limit 20 --status 1 --dry-run   # 先看要审核哪些
CORP_ID=<ID> $PY audit_run.py --limit 20 --status 1             # 真实审核
#   → 记下 audit_report.json 里的 article id，供下一步 --ids 精确锁定

# 1. 生成映射表（默认从历史媒体挑，按价格升序省钱；用 --media-ids 指定主题相关媒体）
CORP_ID=<ID> $PY build_map.py --candidate-source history --sort price --top-k 5 \
    --ids "247059,247058,..." --out map.json
#   也可用白名单精确指定历史媒体（保序、不重排）：
CORP_ID=<ID> $PY build_map.py --candidate-source history \
    --media-ids "300527,294472,50494,19557,172966" --top-k 5 \
    --ids "247059,..." --out map.json

# 2. 先试运行确认无误（不扣豆、不发布）
$PY publish_run.py --map map.json --dry-run

# 3. ★ 把 map.json 交给用户确认（媒体 + 成本）后，再真实发布
CORP_ID=<ID> $PY publish_run.py --map map.json

# 4. 核对发布结果（读真实 publish_status，应全为 3=已发布；禁用媒体失败则换备用重试）
CORP_ID=<ID> IDS="247059,..." $PY verify_publish.py
```

## 典型实战记录（可作为模板参考）

- **corp 4104 上海鹰角塔罗斯（二次元游戏）**：20 篇待审核 → audit_run 审核 20/20 → `--sort price --top-k 5` 分散铺量，成本 25608 智豆（原热度方案 16.1 万，因 quote_cnt 坏数据退化）。
- **corp 3049 贵阳脉通血管医院（静脉曲张）**：10 篇待发布（最新 4 篇已 `pub=3` 自动排除）→ 5 个医疗历史媒体（非常健康网/丁香园/复禾健康-知乎/搜狐医疗/咸宁名医网）轮转 → 丁香园、咸宁名医网**已被禁用**，改用人民网健康、光明医疗网补齐 → 10/10 成功，共 19600 智豆。
  - 关键教训：**历史媒体会被平台禁用**，多发前务必小批量试或接受失败重试。
- **corp 543 中泰期货（期货开户）**：7 个同名 corp 中仅 543 有文章（其余为空壳）。锚定标题「中泰期货：独立交易员参考选项的期货交易软件下载平台」恰为待发布列表最新一篇；取最新 5 篇（均为 `pub=0&audit=1`），从历史记录挑 5 个金融平台（雪球/东方财富/新浪/知乎/百家号）各 1 篇。API 首发因「账户余额不足」失败（后用户确认**智豆不限量**，疑瞬时异常）；用户手动发 3 篇、脚本补发 2 篇，5 篇全部进入发布流程（3 已发布 + 2 发布中）。
  - 修正：用户 2026-07-20 明确智豆不限量；默认候选源已改 `history`（即后台「历史记录」面板）；选媒体以主题相关/权威优先，不为省钱妥协。

## 注意事项

- 发布动作不可逆，执行 `publish_run.py`（无 --dry-run）前务必把 `map.json` 交用户确认（智豆不限量，但仍须用户确认媒体选择）。
- 默认热度指标 `media.quote_cnt` 实测基本是坏的，别用它排序；媒体从「历史记录」里挑、按主题相关性优先（智豆不限量，不必为省钱妥协权威性）。
- 切换公司：设 `CORP_ID` 环境变量，脚本自动调用 `changecorp`。
- `corp_name` 从 `/user/current` 取不到时显示「未知」，不影响发布（以 corp_id 为准）。
- 同一账号下多个公司可能有**重复公司名**（如鹰角塔罗斯有 4104 新 / 130 旧），`companies.txt` 里查 corp_id 时以数字为准，必要时跟用户确认用哪个。
- 本技能通过 git 管理（见仓库 README），便于复用与更新；发布动作涉及真金白银，任何改动的发布脚本请先 --dry-run。
