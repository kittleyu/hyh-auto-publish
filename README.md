# hyh-auto-publish — 360智见 GEO 自动发文 skill

把 360智见（huiyouhua.com）运营后台指定公司的文章，**审核通过 → 从历史媒体里挑主题相关信源 → 生成映射表 → 确认后批量发布**。

> 完整接口、字段结构、踩坑记录见 [`SKILL.md`](./SKILL.md)。

## 前置条件
- 已登录的 Chrome，开启 remote debugging（端口 `9222`）。
- WorkBuddy 托管的 Python venv（已装 `playwright`）；系统自带 Python 无 playwright。
- 后台账号密码**通过环境变量传入，不要写死在脚本里**：
  ```bash
  set HYH_USER=<你的后台账号>
  set HYH_PWD=<你的后台密码>
  ```
- 切换公司用环境变量 `CORP_ID=<公司 corp_id>`（对照见 `companies.txt`）。

## 快速开始
```bash
PY="<托管 venv>/Scripts/python.exe"   # 例: .../.workbuddy/binaries/python/envs/default/Scripts/python.exe
cd <本 skill 目录>

# 0. 文章还是「待审核」时，先批量审核通过（不扣智豆）
CORP_ID=<ID> $PY audit_run.py --limit 20 --status 1 --dry-run   # 先看要审核哪些
CORP_ID=<ID> $PY audit_run.py --limit 20 --status 1             # 真实审核

# 1. 从历史媒体里生成「文章→媒体」映射（默认按价格升序省钱）
CORP_ID=<ID> $PY build_map.py --candidate-source history --sort price --top-k 5 \
    --ids "<article_id 逗号分隔>" --out map.json
#    也可用 --media-ids "<媒体id>" 精确指定主题相关媒体（保序、不重排）

# 2. 先试运行确认，再真实发布（真实发布会扣智豆，务必先看 map.json）
$PY publish_run.py --map map.json --dry-run
$PY publish_run.py --map map.json

# 3. 核对发布结果（直接读每篇真实 publish_status 字段）
CORP_ID=<ID> IDS="<article_id 逗号分隔>" $PY verify_publish.py
```

## 脚本清单
| 脚本 | 作用 |
|---|---|
| `build_map.py` | 生成「文章→媒体」映射表（支持历史媒体 / 白名单 / 按价格排序） |
| `publish_run.py` | 读取映射表批量发布（含 `--dry-run`） |
| `audit_run.py` | 批量审核通过「待审核」文章（不扣豆） |
| `verify_publish.py` | 逐篇核对真实发布状态 |
| `media_probe.py` | 探查候选媒体池 quote_cnt / price 分布 |
| `inspect_history.py` | 查看某 corp 的发文历史媒体清单 |
| `test_dispatch_api.py` | 单篇发布接口连通性测试 |
| `companies.txt` | corp_id ↔ 公司名对照表（**已去敏模板**：仅含占位 corp_id，请替换为你自己账号下真实的 corp_id 与公司名） |

## 已知坑（发布前务必看 [`SKILL.md`](./SKILL.md)）
- 平台 `quote_cnt` 热度数据基本失效，按价格 / 主题相关性选媒体更稳。
- 文章列表的 `publish_status` / `order_id` 过滤参数被后端忽略，核对请用 `verify_publish.py` 读真实字段。
- 历史媒体可能被平台禁用（发布返回「媒体ID 已被禁用」），发前建议小批量试或接受失败重试。

## 安全说明
- **本仓库不含任何账号密码 / 私钥**。凭据一律经环境变量传入，请勿提交明文。
- 发布到 GitHub 使用 SSH deploy key（每仓库一把独立密钥），私钥在本地 `~/.ssh`，不进仓库。
- `_archive/`（开发期探查脚本）与运行时生成的 `*.json` 产物已被 `.gitignore` 排除。
- `companies.txt` 为**去敏模板**，仅含占位 corp_id，不含任何真实客户名称；请按需替换为你自己账号下真实的 corp 列表。运行技能时用 `CORP_ID=<目标corp_id>` 指定公司即可。
