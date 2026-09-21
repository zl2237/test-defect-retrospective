# 测试缺陷复盘与文档评审 Skill 工具包

可复用 AI Skill + 本地 Python 脚本，按输入目录自动路由两种模式（纯文件处理，无 Web/服务端/数据库，所有输入目录可选，scan 自动判定模式）：

- **复盘模式**（defects/ 有导出）：解析 Jira/禅道导出，统一口径计算全量指标，产出**产品/开发/测试**三类复盘报告（MD+JSON+汇总 HTML）
- **定性评审模式**（defects/ 为空）：requirements / test_cases / tech_designs 有文件即触发对应评审——**需求/用例/技术方案评审**（可组合，md 交付）

- 环境：Python 3.8+；读 Excel 需 `pip install openpyxl`（CSV 无依赖）
- 指标口径、产物章节模板、交互流程详见 `SKILL.md`

## 目录结构

```
test-defect-retrospective/
├── SKILL.md                     # Skill 主定义（模式路由/问卷流程/指标口径/评审框架）
├── README.md                    # 本文件
├── .session.json                # 问卷会话状态（自动生成，支持断点续跑）
└── scripts/
    ├── cli.py                   # CLI 入口：session / init / scan(模式路由) / parse / analyze / html / all
    ├── normalize.py             # 值级标准化（状态/严重度/优先级/根因/时间/相似度）
    ├── analyzer.py              # 全量指标计算 + XMind 用例解析（确定性，同输入必同输出）
    ├── reporter.py              # 三类产物渲染（MD+JSON）+ 仪表板/文档双模式 HTML
    ├── docx_extract.py          # docx 文本提取（标准库，含删除线检测）
    ├── custom_field_map.json    # 自定义平台字段映射（问卷选「其他」时生成）
    └── parsers/                 # 插件化解析器（新增平台只加插件，不改主逻辑）
        ├── __init__.py          # 注册表 + 平台自动探测
        ├── base.py              # 基类：CSV/Excel 读取、字段映射
        ├── jira.py / zentao.py / custom.py
```

## 使用步骤

1. **加载 Skill**：交互式问卷 4 题（缺陷平台/发布时间/上版数据/角色名单，每题均影响分析执行，支持断点续跑）；文件格式无需告知，解析器自动识别。
2. **初始化目录**：确认项目名/版本号后创建标准输入目录：

```
{项目名}/
└── {版本号}/
    ├── defects/          # 【可选·复盘模式触发】缺陷平台导出（CSV/Excel）
    ├── requirements/     # 【可选】需求文档 → 需求评审
    ├── test_cases/       # 【可选】测试用例 → 用例评审
    ├── tech_designs/     # 【可选】技术方案（docx/md/txt）→ 技术评审
    ├── 人员角色.csv      # 【建议】姓名,角色（前端/后端/产品/测试）
    └── reports/          # 【输出】自动生成的复盘/评审报告
```

3. **放入文件，执行分析**（Skill 自动串联，亦可手动；scan 输出 `mode` 字段：retrospective=复盘 / review=评审）：

```bash
python scripts/cli.py scan    --root "项目A/v2.4.0"        # 素材校验 + 模式路由
python scripts/cli.py parse   --root "项目A/v2.4.0"        # 解析→标准中间数据集
python scripts/cli.py analyze --root "项目A/v2.4.0" \
       --release-time "2026-09-01 10:00"                   # 全量指标 + 三类产物
python scripts/cli.py html    --root "项目A/v2.4.0"        # 汇总仪表板（复盘模式）
```

4. **AI 定性补充**：脚本产出量化数据后，Skill 对【AI分析】章节补充定性内容（报告风格、需求质量四维、漏测风险、改进项校验等）；补充完重跑 `html` 即可纳入。

- **幂等运行**：报告带时间戳，重复运行不覆盖历史、不改任何原始输入文件。

## 输入输出说明

**输入**（全部可选，按需放置）：

| 输入 | 格式与要点 |
|---|---|
| defects/ | Jira/禅道导出（CSV/xlsx），或 `jira_fetch.py` PAT 拉取产物（走 custom 解析）；明细表放 `defects/明细/` 子目录 |
| requirements/ | docx（自动提取，含删除线识别）/ md / txt；MHTML 伪 .doc 先用 `mht_extract.py` 转换；可含 `需求变更记录.csv`（需求ID、变更内容） |
| test_cases/ | CSV/Excel/XMind（中心主题=套件、叶子=用例、优先级图标→P0~P3，兼容 XMind 8 与 Zen）；表格识别列：编号/标题/模块/关联需求/执行状态/是否回归/执行时长/阻塞原因 |
| tech_designs/ | docx / md / txt |
| 人员角色.csv | `姓名,角色`（前端/后端/产品/测试）；提供后人员效能按真实角色分组、混入角色自动剔除，未提供按近似口径并警示 |
| 上一版本目录 | 同项目下按版本号语义排序自动探测，读取其指标 JSON 做环比 |

**输出**（reports/ 下，均带时间戳，命名 `{系统名}_{迭代号}_{产物分类}_{ts}`）：

- `复盘报告_产品/开发/测试_{ts}.md/.json` —— 三类复盘报告（产品 8 章 / 开发 7 章 / 测试 14 章）
- `复盘数据_指标全量_{ts}.json` —— 全量指标结构化数据（供工具调用与下版本环比）
- `复盘报告_汇总_{ts}.html` —— 单文件自包含仪表板（零外部依赖，离线打开/迁移分享，支持打印分页）
- `需求/用例/技术评审报告_{ts}.md` —— 评审模式产物（如需档案风 HTML 可选 `html --doc <md路径>`）

数据缺失的章节统一标注：`⚠️ 【数据缺失】缺少XX文件/字段，该项暂无法分析`。

## 字段映射说明

解析器将平台原始表头映射为标准字段（bug_id / title / status / severity / priority / module / reporter / assignee / created_at / resolution / root_cause / reopen_count 等），再经 `normalize.py` 值级标准化（状态组/严重度/优先级/解决结果/根因/偶现识别），输出与源平台解耦的中间数据集。完整字段对照见 `SKILL.md` 附录A。

- **自定义平台**：问卷选「其他」→ 按用户字段说明生成 `scripts/custom_field_map.json`（格式见附录C）→ custom 插件解析
- **新增平台**：`scripts/parsers/` 新增 `BaseParser` 子类（定义 `name`/`field_map`/`signature_headers`）并注册，主分析逻辑零改动

## 常见问题

- **中文乱码**：CSV 自动按 utf-8/GB18030/utf-16 探测；仍失败请用 UTF-8 重导出
- **Excel 读取失败**：`pip install openpyxl`，或改用 CSV
- **表头未识别**：核对导出字段名；Jira/禅道自定义字段走 custom 映射
- **环比无数据**：确认上一版本 reports/ 下存在 `复盘数据_指标全量_*.json`
- **HTML 未含最新 AI 定性**：AI 补充完 md 后重跑 `html`
- **docx 提取失败**：确认是 .docx（非 .doc 老格式）；内嵌图片不参与提取
- **判定复盘还是评审**：看 scan 输出 `mode` 字段（retrospective / review）
- **XMind 解析范围**：detached 游离主题不统计；XMind 无执行状态与回归标记，相关指标按缺失/「未执行」口径标注

## 工具脚本

| 脚本 | 用途 |
|---|---|
| `scripts/jira_fetch.py` | PAT 按 sprint/JQL 拉取缺陷主表+活动日志+评论（标准库实现）；主表全字段补齐（分配/解决/关闭时间、重开次数等自 changelog 派生），明细自动落 `defects/明细/`，并生成 `人员角色_模板.csv` |
| `scripts/mht_extract.py` | MHTML 伪 .doc（网页另存为 Word 的常见产物）→ 纯文本 |
| `scripts/docx_extract.py` | OOXML docx → 纯文本（含删除线检测） |
| `scripts/custom_field_map.json` | 内置「Jira API 拉取表头 → 标准字段」映射，配合 `parse --platform custom` |

```bash
# PAT 拉取示例（PAT 亦可由环境变量 JIRA_PAT 提供）
python scripts/jira_fetch.py --base http://jira.example.com --project WLXT --sprint 21 --out "物流管理系统/v1.5.0/defects"
# 随后正常走 scan → parse --platform custom → analyze → html
```
