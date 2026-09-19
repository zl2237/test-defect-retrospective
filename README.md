# 测试缺陷复盘 Skill 工具包

## 项目目标

可复用 AI Skill + 本地预置 Python 解析脚本，面向**版本测试缺陷复盘**场景：解析 Jira / 禅道缺陷导出文件，按统一口径计算全量分析指标，自动产出**产品 / 开发 / 测试**三类复盘报告（Markdown + JSON 双格式）。纯文件处理：无 Web 平台、无服务端、无数据库。

- 环境要求：Python 3.8+；读取 Excel（.xlsx）需 `pip install openpyxl`（CSV 无需依赖）。
- 完整指标口径、产物章节模板、交互流程见 `SKILL.md`。

## 目录结构

```
test-defect-retrospective/
├── SKILL.md                     # Skill 主定义（问卷流程/指标口径/产物模板/规则）
├── README.md                    # 本文件
├── .session.json                # 问卷会话状态（自动生成，支持断点续跑）
└── scripts/
    ├── cli.py                   # CLI 入口：session / init / scan / parse / analyze / all
    ├── normalize.py             # 值级标准化（状态/严重度/优先级/根因/时间/相似度）
    ├── analyzer.py              # 全量指标计算（确定性，同输入必同输出）
    ├── reporter.py              # 三类产物渲染（MD+JSON，时间戳幂等）
    ├── custom_field_map.json    # 自定义平台字段映射（问卷选「其他」时生成）
    └── parsers/                 # 插件化解析器（新增平台只加插件，不改主逻辑）
        ├── __init__.py          # 注册表 + 平台自动探测
        ├── base.py              # 基类：CSV/Excel 读取、字段映射
        ├── jira.py              # Jira 解析插件
        ├── zentao.py            # 禅道解析插件
        └── custom.py            # 自定义平台插件（读 custom_field_map.json）
```

## 使用步骤

1. **加载 Skill**：自动进入交互式问卷（5 题，支持分支追问与断点续跑），收集缺陷平台、需求托管平台、需求格式、用例来源、上一版本报告信息。
2. **初始化目录**：确认项目名/版本号后，自动创建标准输入目录：

```
{项目名}/
└── {版本号}/
    ├── defects/          # 【必填】缺陷平台导出文件（CSV/Excel）
    ├── requirements/     # 【可选】需求文档全量文件
    ├── test_cases/       # 【可选】测试用例文件
    ├── 人员角色.csv      # 【建议】姓名,角色（角色：前端/后端/产品/测试）
    └── reports/          # 【输出】自动生成的复盘报告
```

3. **放入文件**：将缺陷导出、需求文档、测试用例放入对应子目录。
4. **执行分析**（Skill 自动串联，也可手动执行）：

```bash
python scripts/cli.py scan   --root "项目A/v2.4.0"                 # 素材校验（缺失清单）
python scripts/cli.py parse  --root "项目A/v2.4.0"                 # 解析→标准中间数据集
python scripts/cli.py analyze --root "项目A/v2.4.0" \
       --release-time "2026-09-01 10:00"                          # 全量指标+三类产物
```

5. **AI 定性补充**：脚本产出量化数据后，Skill 对标注【AI分析】的章节补充定性内容（语言风格分析、需求质量四维评估、漏测风险、自动化分层建议、改进项校验等）。

- **最小输入集**：仅 `defects/` 即可产出开发、测试类核心产物（需求类章节标注缺失）。
- **幂等运行**：报告文件带时间戳，重复运行不覆盖历史、不修改任何原始输入文件。

## 输入输出说明

| 目录/文件 | 说明 | 可选性 |
|---|---|---|
| defects/ | Jira/禅道/自定义平台导出（CSV 或 xlsx） | 必填 |
| 人员角色.csv | 团队角色名单（列：`姓名,角色`；角色取值：前端/后端/产品/测试，支持 qa/fe/be/pm 等别名）。提供后人员效能按真实角色分组：仅「测试」计入提报/验证效能、仅「前端/后端」计入修复效能，混入角色（如测试自解决缺陷）自动剔除并标注条数；未提供时按近似口径并警示 | 建议 |
| requirements/ | 需求文档；如含 `需求变更记录.csv`（列：需求ID、变更内容）可统计变更连锁缺陷 | 可选 |
| test_cases/ | 用例文件，识别列：用例编号/标题/所属模块/关联需求/执行状态(通过/失败/阻塞/跳过/未执行)/是否回归/执行时长(分钟)/阻塞原因 | 可选 |
| 上一版本目录 | 同项目下按版本号语义排序自动探测，读取其 reports/ 指标 JSON 做环比 | 可选 |

**输出**（reports/ 下，均带时间戳）：

- `复盘报告_产品_{ts}.md/.json` —— 8 个固定章节（需求评审、变更连锁、加急质量、依赖缺失、需求溯源、交互体验、遗留风险等）
- `复盘报告_开发_{ts}.md/.json` —— 7 个固定章节（大盘、根因、偶现清单、修复时效分层、回弹率、重复缺陷根因、流程建议）
- `复盘报告_测试_{ts}.md/.json` —— 14 个固定章节（提报效能、验证率、环比、改进项校验、覆盖率、阻塞、回归、漏测风险、自动化清单等）
- `复盘数据_指标全量_{ts}.json` —— 全量指标结构化数据（供其他工具调用与下版本环比）

数据缺失的章节统一标注：`⚠️ 【数据缺失】缺少XX文件/字段，该项暂无法分析`。

## 字段映射说明

解析器将平台原始表头映射为标准字段后，再由 `normalize.py` 做值级标准化（状态组 / 严重度 / 优先级 / 解决结果 / 根因 7 类 / 偶现识别），输出与源平台解耦的标准中间数据集。

**标准字段与预置映射**（完整对照见 `SKILL.md` 附录A）：

| 标准字段 | Jira 表头 | 禅道表头 | 值标准化 |
|---|---|---|---|
| bug_id | Issue key / 问题键 | ID / Bug编号 | 原样 |
| title | Summary / 摘要 | Bug标题 | 原样（相似度指纹用于重复识别） |
| status | Status | 状态 / 当前状态 | open/in_progress/resolved/closed |
| severity | Severity / 严重级别 | 严重程度(1-4) | 致命/严重/一般/轻微/建议 |
| priority | Priority | 优先级(1-4) | P0/P1/P2/P3 |
| module | Components / 模块 | 模块 / 所属模块 | 原样 |
| reporter / assignee / resolver / verifier | Reporter / Assignee / Resolver / Verifier | 创建者 / 指派给 / 由谁解决 / 关闭者 | 原样 |
| created_at / assigned_at / resolved_at / closed_at | Created / Assigned / Resolved / Closed | 创建日期 / 指派日期 / 解决日期 / 关闭日期 | 多格式解析 |
| resolution | Resolution | 解决方案 | 已修复/重复/设计如此/无法重现/无效/转需求/延期处理 |
| root_cause | Root Cause / 根因 | 根因 | 7 类预置 + 未分类 |
| reopen_count | Reopen / 重开次数 | 激活次数 | 整数 |
| labels / requirement_id / repro / remark / duplicate_of | Labels / 需求ID / 复现概率 / Description / Duplicate of | 关键词 / 关联需求 / 复现概率 / 复现步骤 / 重复关联 | 见 normalize.py |

**自定义平台**：问卷选择「其他」后，按用户提供的字段说明生成 `scripts/custom_field_map.json`（原始表头 → 标准字段，格式见 `SKILL.md` 附录C），custom 插件即可解析。

**新增平台**：在 `scripts/parsers/` 新增 `BaseParser` 子类（定义 `name` / `field_map` / `signature_headers`）并注册到 `PARSER_REGISTRY`，主分析逻辑零改动。

## 常见问题

- **中文乱码 / 编码报错**：CSV 自动按 utf-8 / GB18030 / utf-16 探测；仍失败时请用 UTF-8 重新导出。
- **Excel 读取失败**：安装 `pip install openpyxl`，或改用 CSV 导出。
- **表头未被识别**：核对导出字段名与映射表；Jira/禅道自定义字段请走 custom 映射。
- **环比无数据**：确认上一版本目录的 reports/ 下存在 `复盘数据_指标全量_*.json`。
