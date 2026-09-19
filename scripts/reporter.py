# -*- coding: utf-8 -*-
"""报告生成模块：渲染 3 大类产物（MD+JSON）与单文件汇总 HTML。

规则：
- 章节结构与 SKILL.md 第四节完全一致，不得增减；
- 双格式输出：Markdown 可读报告 + JSON 结构化数据（+汇总 HTML，零外部依赖）；
- 文件名带时间戳，幂等运行不覆盖历史报告；
- 数据缺失的章节末尾统一标注：⚠️ 【数据缺失】缺少XX文件/字段，该项暂无法分析；
- AI 定性内容以「【AI分析】」占位标记预留，由 Skill 侧追加补充。
"""
import json
import os
import time

MISSING_MARK = '⚠️ 【数据缺失】'
AI_MARK = '【AI分析】'


def _ts():
    return time.strftime('%Y%m%d_%H%M%S')


def _unique_path(path):
    """同秒重复运行时追加序号，保证幂等不覆盖。"""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists('%s_%d%s' % (base, i, ext)):
        i += 1
    return '%s_%d%s' % (base, i, ext)


def _table(rows, headers=None):
    """list[dict] → Markdown 表格；空数据返回占位说明。"""
    if not rows:
        return '（无数据）'
    headers = headers or list(rows[0].keys())
    lines = ['| ' + ' | '.join(str(h) for h in headers) + ' |',
             '|' + '|'.join(['---'] * len(headers)) + '|']
    for r in rows:
        lines.append('| ' + ' | '.join(str(r.get(h, '')) for h in headers) + ' |')
    return '\n'.join(lines)


def _missing_line(reason):
    return '> %s 缺少%s，该项暂无法分析' % (MISSING_MARK, reason)


def _ai_placeholder(hint):
    return '> %s（待AI补充）：%s' % (AI_MARK, hint)


def _brief_table(items, limit=200):
    """缺陷清单摘要表。"""
    rows = [{'编号': i.get('bug_id'), '标题': i.get('title'), '模块': i.get('module'),
             '严重程度': i.get('severity'), '状态': i.get('status_group'),
             '提报人': i.get('reporter')}
            for i in (items or [])[:limit]]
    return _table(rows)


# ---------------------------------------------------------------------------
# 产物一：产品侧
# ---------------------------------------------------------------------------

def build_product(m):
    meta, req, ov = m['meta'], m['requirement'], m['overview']
    has_req_doc = not any('需求文档' in x for x in m['missing'])
    sec = {}

    sec['一、需求文档评审结论'] = (
        _ai_placeholder('逻辑自洽性 / 重复赘述 / 文案可读性 / 提示语清晰度 四维评估')
        if has_req_doc else _missing_line('requirements/ 需求文档文件'))

    sec['二、模块缺陷与需求问题关联分析'] = _table(
        req['module_req_issues']) if req['module_req_issues'] else (
        _table(req['module_req_issues']) + '\n' +
        _missing_line('缺陷根因字段（无法定位需求侧根因）'))

    if req['change_stats']:
        cs = req['change_stats']
        sec['三、需求变更统计与变更连锁缺陷分析'] = (
            '需求变更总频次：**%s** ｜ 变更需求数：**%s** ｜ 连锁缺陷总数：**%s**（占比 %s%%）\n\n%s'
            % (cs['变更总频次'], cs['变更需求数'], cs['连锁缺陷总数'],
               cs['连锁缺陷占比(%)'], _table(cs['变更明细'])))
    else:
        sec['三、需求变更统计与变更连锁缺陷分析'] = (
            _missing_line('requirements/需求变更记录.csv 文件（含需求ID、变更内容列）'))

    u = req['urgent_bugs']
    sec['四、临时加急需求质量评估'] = (
        '临时加急关联缺陷：**%s** 条，占总缺陷 **%s%%**\n\n%s\n\n%s'
        % (u['count'], u['rate(%)'], _brief_table(u['items']),
           _ai_placeholder('结合需求文档评估临时加急需求的质量风险'))
        if u['count'] else
        '未在缺陷标题/标签/备注中识别到「加急/临时」标记缺陷。\n\n'
        + _ai_placeholder('如确有临时加急需求，请提供需求清单后补充评估'))

    d = req['dependency_bugs']
    sec['五、上下游依赖缺失评估'] = (
        '上下游依赖/联调类缺陷：**%s** 条，占比 **%s%%**\n\n%s\n\n%s'
        % (d['count'], d['rate(%)'], _brief_table(d['items']),
           _ai_placeholder('评估依赖缺失原因与协作机制改进建议'))
        if d['count'] else
        '未在缺陷标题/备注中识别到上下游依赖/联调关键词缺陷。')

    r = req['req_introduced']
    sec['六、需求引入类缺陷溯源与占比'] = (
        '根因=需求问题的缺陷：**%s** 条，占有效缺陷 **%s%%**\n\n%s'
        % (r['count'], r['rate(%)'], _brief_table(r['items']))
        if r['count'] else
        '未识别到根因为「需求问题」的缺陷（需缺陷导出含根因字段）。')

    sec['七、产品交互体验评估与优化建议'] = (
        _ai_placeholder('基于需求文档与缺陷分布评估交互体验合理性')
        if has_req_doc else _missing_line('requirements/ 需求文档文件'))

    lg = ov['legacy']
    if lg['count']:
        sec['八、历史遗留缺陷风险提示'] = (
            '存量遗留缺陷：**%s** 条（发布时间基准：%s，口径：%s）\n\n%s'
            % (lg['count'], lg['release_time'] or '未知', lg['release_time_source'] or '-',
               _brief_table(lg['items'])))
    elif '发布时间' in ''.join(m['missing']):
        sec['八、历史遗留缺陷风险提示'] = _missing_line('发布时间与创建时间字段')
    else:
        sec['八、历史遗留缺陷风险提示'] = '未发现创建于本版本发布之前且未关闭的存量遗留缺陷。'
    return sec


# ---------------------------------------------------------------------------
# 产物二：开发侧
# ---------------------------------------------------------------------------

def build_dev(m):
    ov, ps = m['overview'], m['personnel']
    sec = {}

    head = ('Bug总数 **%s** ｜ 无效缺陷 **%s** ｜ 有效缺陷 **%s** ｜ 已关闭 **%s** ｜ '
            'Bug解决率 **%s%%**' % (ov['bug_total'], ov['invalid_total'], ov['valid_total'],
                                    ov['closed_total'], ov['resolved_rate(%)']))
    sec['一、缺陷大盘全量数据'] = (
        head + '\n\n**按严重程度**\n\n' + _table(ov['by_severity'])
        + '\n\n**按业务优先级**\n\n' + _table(ov['by_priority'])
        + '\n\n**按业务模块**\n\n' + _table(ov['by_module'])
        + '\n\n**规律性反复缺陷（同模块/同根因连续≥2版本出现）**\n\n'
        + (_table(ov['recurring']) if ov['recurring'] is not None else
           (_table(ov['recurring'] or []) + '\n' + _missing_line('上一版本缺陷数据'))))

    rc = ov['root_cause']
    sec['二、缺陷根因分类统计'] = (
        _table(rc) + '\n\n' + _ai_placeholder('针对TOP根因的开发侧改进分析')
        if rc else _table(rc) + '\n' + _missing_line('缺陷根因字段'))

    oc = ov['occasional']
    sec['三、偶现缺陷清单'] = (
        '偶现缺陷 **%s** 条（占比 %s%%，口径：备注含难以复现/偶现 或 复现概率<30%%）\n\n%s'
        % (oc['count'], oc['rate(%)'], _brief_table(oc['items']))
        if oc['count'] else '未识别到偶现缺陷。')

    dev_rows = [{'开发人员': d['开发人员'], '角色': d.get('角色', '-'),
                 '已修复总数': d['已修复总数'],
                 '平均修复时长(小时)': d['平均修复时长(小时)'],
                 '缺陷回弹率(%)': d['缺陷回弹率(%)']}
                for d in ps['devs']]
    layered = []
    for d in ps['devs']:
        for sev, h in (d.get('分层修复时长') or {}).items():
            layered.append({'开发人员': d['开发人员'], '角色': d.get('角色', '-'),
                            '严重程度': sev,
                            '平均修复时长(小时)': h})
    sec['四、开发个人修复时效（按严重等级分层）'] = (
        _table(dev_rows) + '\n\n**按严重等级分层**\n\n' + _table(layered)
        if dev_rows else _table(dev_rows) + '\n' +
        _missing_line('解决时间/分配时间字段，无法计算修复时效'))

    bounce_rows = [{'开发人员': d['开发人员'], '角色': d.get('角色', '-'),
                    '已修复总数': d['已修复总数'],
                    '回弹数(重开>0)': round(d['已修复总数'] * d['缺陷回弹率(%)'] / 100)
                    if d['缺陷回弹率(%)'] is not None else None,
                    '缺陷回弹率(%)': d['缺陷回弹率(%)']} for d in ps['devs']]
    sec['五、缺陷回弹率统计'] = _table(bounce_rows)

    dup = ov['duplicates']
    if dup['groups']:
        sec['六、高频重复缺陷根因分析'] = (
            '重复缺陷 **%s** 条（平台标记 %s 条，占比 %s%%），相似簇 %s 组\n\n%s\n\n%s'
            % (dup['count'], dup['flagged_by_platform'], dup['rate(%)'],
               len(dup['groups']), _table(dup['groups']),
               _ai_placeholder('对高频重复簇补充根因分析与防复发建议')))
    else:
        sec['六、高频重复缺陷根因分析'] = '未发现重复缺陷。'

    sec['七、开发侧流程优化建议'] = _ai_placeholder(
        '基于根因分布/回弹率/修复时效给出流程优化建议（如代码评审重点、自测检查单、 '
        '高频重复缺陷防复发机制）')
    return sec


# ---------------------------------------------------------------------------
# 产物三：测试侧
# ---------------------------------------------------------------------------

def build_test(m):
    ov, ps, tc = m['overview'], m['personnel'], m['testcases']
    auto, risk, cmp = m['automation'], m['risk_scan'], m['compare']
    sec = {}

    # 第一章（提报维度）与第二章（验证维度）列拆分，避免两章渲染同一张全列表格
    report_rows = [{'测试人员': t['测试人员'], '角色': t.get('角色', '-'),
                    '提交Bug数': t['提交Bug数'],
                    '个人占比(%)': t['个人占比(%)']} for t in ps['testers']]
    verify_rows = [{'测试人员': t['测试人员'], '角色': t.get('角色', '-'),
                    '验证总数': t['验证总数'],
                    '首次验证通过率(%)': t['首次验证通过率(%)'],
                    '驳回重修复率(%)': t['驳回重修复率(%)'],
                    '平均验证时长(小时)': t['平均验证时长(小时)']} for t in ps['testers']]
    sec['一、测试人员提报效能全量指标'] = _table(report_rows)

    sec['二、Bug验证通过率与驳回率统计'] = (
        _table(verify_rows) + '\n\n' + _ai_placeholder(
            '对各测试人员 titles_sample 标题采样做 Bug 描述语言风格分析与改良建议')
        if verify_rows else _missing_line('提报人字段'))

    if cmp:
        sec['三、版本环比全量分析'] = (
            '对比基准：上一版本 **%s**\n\n%s\n\n%s'
            % (cmp['prev_version'], _table(cmp['metrics_delta']),
               _ai_placeholder('输出变化点、进步点、核心短板的定性结论')))
    else:
        sec['三、版本环比全量分析'] = _missing_line('上一版本复盘报告/指标数据')

    sec['四、上一轮改进项落地效果校验'] = (
        _ai_placeholder('逐项核对上一版本报告中的改进建议，结合本版本数据给出落地效果结论')
        if cmp else _missing_line('上一版本复盘报告'))

    if tc:
        sec['五、用例覆盖率与需求-用例双向追踪'] = (
            '用例总数 **%s** ｜ 已执行 **%s** ｜ 执行覆盖率 **%s%%**\n\n%s\n\n%s\n\n%s'
            % (tc['case_total'], tc['executed'], tc['exec_coverage(%)'],
               _table(tc['status_dist']),
               '**需求-用例双向覆盖**：缺陷关联需求 %s 个，被用例覆盖 %s 个（%s%%）；'
               '用例关联需求完整率 %s%%'
               % (tc['req_coverage']['缺陷关联需求数'], tc['req_coverage']['被用例覆盖数'],
                  tc['req_coverage']['需求被用例覆盖比例(%)'],
                  tc['req_coverage']['用例关联需求完整率(%)']),
               _table([{'未覆盖需求': x} for x in tc['req_coverage']['未覆盖需求清单']])))
        sec['六、测试阻塞事件统计'] = (
            '阻塞用例 **%s** 条\n\n%s' % (
                tc['blocked_events']['total'],
                _table([{'分类': x['分类'], '数量': x['数量'],
                         '用例': '、'.join(x['用例'][:10])} for x in
                        tc['blocked_events']['by_category']])))
        rg = tc['regression']
        sec['七、回归工作量统计'] = (
            '回归用例数 **%s** ｜ 回归执行时长合计 **%s 分钟**'
            % (rg['regression_case_count'], rg['regression_duration_min']))
    else:
        for title in ('五、用例覆盖率与需求-用例双向追踪', '六、测试阻塞事件统计',
                      '七、回归工作量统计'):
            sec[title] = _missing_line('test_cases/ 测试用例文件')

    gap_table = _table(risk['module_gaps']) if risk['module_gaps'] else '（未发现明显模块缺口）'
    kw_lines = '\n'.join('- %s：%s' % (k, '、'.join(v[:10]))
                         for k, v in risk['keyword_hits'].items())
    sec['八、潜在漏测风险清单'] = (
        ('**高风险场景关键词命中**\n%s\n\n**模块缺陷-用例缺口**\n%s\n\n%s'
         % (kw_lines or '（无命中）', gap_table,
            _ai_placeholder('结合边界/并发/大数据量/弱网场景补充漏测风险清单'))))

    sec['九、测试环境配置差异风险'] = (
        _ai_placeholder('向用户收集测试环境与生产配置差异信息后评估风险；'
                        '用户提供前标注为待补充'))

    sec['十、用例设计短板与优化建议'] = _ai_placeholder(
        '基于用例覆盖缺口、失败分布与缺陷分布给出用例设计优化建议')

    if auto:
        auto_rows = [{'模块': r['模块'], '评分': r['评分'], '优先级': r['优先级'],
                      '投入产出评级': r['投入产出评级'], 'Bug数': r['Bug数'],
                      '用例数': r['用例数'], '回归用例数': r['回归用例数'],
                      '评分维度': r['评分维度']} for r in auto['modules']]
        sec['十一、自动化优先级覆盖清单（接口、UI分层）'] = (
            '评分公式：%s\n\n优先级规则：%s\n\n%s\n\n%s'
            % (auto['formula'], auto['priority_rule'], _table(auto_rows),
               _ai_placeholder('基于模块属性给出接口自动化 / UI自动化分层建议与理由')))
    else:
        sec['十一、自动化优先级覆盖清单（接口、UI分层）'] = _missing_line(
            '缺陷与用例数据（无法计算模块评分）')

    sec['十二、可封装Skill工作清单'] = _ai_placeholder(
        '识别本复盘流程中可复用/重复性高的工作（如数据导出清洗、指标拉取、报告初稿），'
        '给出可封装为新 Skill 的清单')

    lc = ps['lifecycle']
    lc_rows = [{'阶段': k, '平均(小时)': v['平均(小时)'], '样本数': v['样本数']}
               for k, v in lc.items()]
    sec['十三、测试流程改进建议'] = (
        _ai_placeholder('基于全量数据给出测试流程改进建议') +
        '\n\n**缺陷全生命周期各阶段耗时分布**（供流程分析）\n\n' + _table(lc_rows) +
        '\n\n' + '\n\n'.join(
            '**%s 分布**\n%s' % (k, _table(v['分布']))
            for k, v in lc.items() if v['分布']))

    dup = ov['duplicates']
    dup_rows = [{'测试人员': t['测试人员'], '提交Bug数': t['提交Bug数'],
                 '重复上报Bug率(%)': t['重复上报Bug率(%)']} for t in ps['testers']]
    sec['十四、重复上报缺陷率统计'] = (
        '整体重复缺陷率 **%s%%**（%s 条）\n\n%s'
        % (dup['rate(%)'], dup['count'], _table(dup_rows)))
    return sec


# ---------------------------------------------------------------------------
# 渲染与写出
# ---------------------------------------------------------------------------

_BUILDERS = {'产品': build_product, '开发': build_dev, '测试': build_test}


def _render_md(category, m, sections):
    meta = m['meta']
    lines = [
        '# %s %s 测试缺陷复盘报告 —— %s侧' % (meta['project'], meta['version'], category),
        '',
        '> 生成时间：%s ｜ 数据来源：%s导出 ｜ 输入文件：%s'
        % (meta['generated_at'], meta['platform'], '、'.join(meta['input_files']) or '-'),
        '> 发布时间基准：%s（口径：%s）' % (meta['release_time'] or '未知',
                                        meta['release_time_source'] or '-'),
        '',
        '## 缺失素材清单',
        '',
    ]
    if m['missing']:
        lines += ['- %s' % x for x in m['missing']]
    else:
        lines.append('- 无')
    lines.append('')
    for title, body in sections.items():
        lines += ['## ' + title, '', body, '']
    return '\n'.join(lines)


def write_reports(metrics, reports_dir):
    """生成 3 类产物（MD+JSON）+ 指标全量 JSON，返回文件路径清单。"""
    os.makedirs(reports_dir, exist_ok=True)
    ts = _ts()
    meta = metrics['meta']
    out = []
    for category, builder in _BUILDERS.items():
        sections = builder(metrics)
        md_name = '复盘报告_%s_%s.md' % (category, ts)
        json_name = '复盘报告_%s_%s.json' % (category, ts)
        md_path = _unique_path(os.path.join(reports_dir, md_name))
        json_path = _unique_path(os.path.join(reports_dir, json_name))
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(_render_md(category, metrics, sections))
        payload = {
            'category': category,
            'project': meta['project'],
            'version': meta['version'],
            'generated_at': meta['generated_at'],
            'source_platform': meta['platform'],
            'missing': metrics['missing'],
            'sections': sections,
            'summary_core': metrics['summary_core'],
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        out += [md_path, json_path]
    full_path = _unique_path(os.path.join(reports_dir, '复盘数据_指标全量_%s.json' % ts))
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    out.append(full_path)
    return out


# ---------------------------------------------------------------------------
# 汇总 HTML 报告（单文件：内嵌 CSS/JS 与纯 CSS/SVG 图表，零外部依赖，
# 可离线打开、下载、迁移分享；由 cli 的 html 子命令在 AI 定性补充后调用）
# ---------------------------------------------------------------------------

_SEV_COLORS = {'致命': '#dc2626', '严重': '#ea580c', '一般': '#d97706',
               '轻微': '#16a34a', '建议': '#64748b', '未分级': '#94a3b8'}

_HTML_CSS = """
:root{--bg:#f1f5f9;--card:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;
--brand:#4f46e5;--brand-ink:#eef2ff;--ok:#16a34a;--warn:#d97706;--bad:#dc2626}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif;
background:var(--bg);color:var(--ink);line-height:1.6;font-size:14px}
header{background:linear-gradient(135deg,#312e81,#4f46e5 60%,#6366f1);color:#fff;
padding:28px 32px}
header h1{font-size:22px;font-weight:600}
header .meta{margin-top:8px;font-size:12.5px;opacity:.85;display:flex;
flex-wrap:wrap;gap:6px 18px}
nav{position:sticky;top:0;z-index:9;background:#fff;border-bottom:1px solid var(--line);
display:flex;padding:0 16px;overflow-x:auto;box-shadow:0 1px 4px rgba(15,23,42,.06)}
nav button{border:0;background:none;padding:13px 20px;font-size:14px;cursor:pointer;
color:var(--muted);border-bottom:2.5px solid transparent;white-space:nowrap;font-weight:500}
nav button.active{color:var(--brand);border-bottom-color:var(--brand);font-weight:600}
main{max-width:1180px;margin:24px auto;padding:0 20px}
section.panel{display:none}
section.panel.active{display:block;animation:fade .25s}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
h2.sec{font-size:17px;margin:28px 0 10px;padding:8px 12px;background:var(--brand-ink);
border-left:4px solid var(--brand);border-radius:4px}
h3.sub{font-size:14.5px;margin:16px 0 8px;color:#334155}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:12px;margin:16px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;box-shadow:0 1px 3px rgba(15,23,42,.05)}
.card .k{font-size:12px;color:var(--muted)}
.card .v{font-size:22px;font-weight:700;margin-top:4px;color:var(--brand)}
.card .v.plain{color:var(--ink)}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:13px;
border:1px solid var(--line);border-radius:8px;overflow:hidden}
th{background:#f8fafc;text-align:left;padding:8px 10px;font-weight:600;color:#334155;
border-bottom:2px solid var(--line);white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid #f1f5f9;vertical-align:top}
tr:nth-child(even) td{background:#fafbfd}
tr:hover td{background:var(--brand-ink)}
.blockquote,blockquote{background:#fffbeb;border:1px solid #fde68a;border-left:4px solid #f59e0b;
border-radius:6px;padding:10px 14px;margin:10px 0;font-size:13px}
blockquote.ai{background:#f0fdf4;border-color:#bbf7d0;border-left-color:var(--ok)}
.missing-box{background:#fef2f2;border:1px solid #fecaca;border-left:4px solid var(--bad);
border-radius:6px;padding:10px 14px;margin:8px 0;font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.chart-card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px;margin:14px 0;box-shadow:0 1px 3px rgba(15,23,42,.05)}
.chart-card h3{font-size:14px;margin-bottom:12px;color:#334155}
.legend{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;font-size:12.5px}
.legend span.dot{display:inline-block;width:10px;height:10px;border-radius:3px;
margin-right:5px;vertical-align:-1px}
.bar-row{display:flex;align-items:center;gap:10px;margin:6px 0;font-size:12.5px}
.bar-row .name{width:200px;flex:none;text-align:right;color:#334155;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-row .track{flex:1;background:#f1f5f9;border-radius:5px;height:18px;overflow:hidden}
.bar-row .fill{height:100%;border-radius:5px;background:linear-gradient(90deg,#6366f1,#4f46e5);
min-width:2px;color:#fff;font-size:11px;line-height:18px;padding-left:6px}
.bar-row .val{width:64px;flex:none;color:var(--muted)}
.donut-wrap{display:flex;align-items:center;gap:22px;flex-wrap:wrap}
ul,ol{margin:8px 0 8px 22px}
li{margin:3px 0}
p{margin:8px 0}
footer{max-width:1180px;margin:30px auto 40px;padding:14px 20px;color:var(--muted);
font-size:12px;border-top:1px solid var(--line)}
.badge{display:inline-block;background:#e0e7ff;color:#4338ca;border-radius:10px;
padding:1px 9px;font-size:11.5px;margin-left:8px;font-weight:500}
#toTop{position:fixed;right:22px;bottom:26px;width:40px;height:40px;border-radius:50%;
border:0;background:var(--brand);color:#fff;font-size:16px;cursor:pointer;
box-shadow:0 4px 12px rgba(79,70,229,.4);display:none}
@media print{nav,#toTop{display:none}section.panel{display:block!important;page-break-after:always}
body{background:#fff}}
"""


def _esc(s):
    return (str(s if s is not None else '').replace('&', '&amp;')
            .replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def _md_inline(s):
    """行内 Markdown → HTML（加粗；**成对出现时安全）。"""
    s = _esc(s)
    parts = s.split('**')
    return ''.join(p if i % 2 == 0 else '<strong>%s</strong>' % p
                   for i, p in enumerate(parts))


def md_block_to_html(md):
    """轻量 Markdown 块 → HTML（表格/引用/列表/标题/段落），供 HTML 汇总报告使用。"""
    lines = str(md or '').split('\n')
    html, i, para = [], 0, []

    def flush_para():
        if para:
            html.append('<p>%s</p>' % _md_inline(' '.join(para)))
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush_para(); i += 1; continue
        # 表格
        if line.lstrip().startswith('|') and i + 1 < len(lines) and \
                set(lines[i + 1].replace('|', '').replace('-', '').strip()) <= set(': '):
            flush_para()
            headers = [c.strip() for c in line.strip().strip('|').split('|')]
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            t = ['<table><thead><tr>'] + ['<th>%s</th>' % _md_inline(h) for h in headers] + \
                ['</tr></thead><tbody>']
            for r in rows:
                t.append('<tr>' + ''.join('<td>%s</td>' % _md_inline(c) for c in r) + '</tr>')
            t.append('</tbody></table>')
            html.append(''.join(t)); continue
        # 引用块（连续 > 行合并；含【AI分析】使用绿色样式）
        if line.lstrip().startswith('>'):
            flush_para()
            block, is_ai = [], False
            while i < len(lines) and lines[i].lstrip().startswith('>'):
                c = lines[i].lstrip()[1:].strip()
                if '【AI分析】' in c:
                    is_ai = True
                block.append(c)
                i += 1
            cls = ' class="ai"' if is_ai else ''
            inner = ''.join('<p>%s</p>' % _md_inline(b) if b else '' for b in block)
            html.append('<blockquote%s>%s</blockquote>' % (cls, inner)); continue
        # 小标题（###/####）
        if line.lstrip().startswith('###'):
            flush_para()
            html.append('<h3 class="sub">%s</h3>' % _md_inline(line.lstrip()[3:].strip()))
            i += 1; continue
        # 无序列表
        if line.lstrip().startswith(('- ', '* ')):
            flush_para()
            items = []
            while i < len(lines) and lines[i].lstrip().startswith(('- ', '* ')):
                items.append('<li>%s</li>' % _md_inline(lines[i].lstrip()[2:]))
                i += 1
            html.append('<ul>%s</ul>' % ''.join(items)); continue
        # 有序列表（n. / n、）
        if len(line.lstrip()) > 2 and line.lstrip()[0].isdigit() \
                and line.lstrip()[1:3][:1] in ('.', '、'):
            flush_para()
            items = []
            while i < len(lines) and lines[i].lstrip()[:1].isdigit() and \
                    lines[i].lstrip()[1:3][:1] in ('.', '、'):
                c = lines[i].lstrip()
                items.append('<li>%s</li>' % _md_inline(
                    c[2:].strip() if c[1] in '.、' else c[3:].strip()))
                i += 1
            html.append('<ol>%s</ol>' % ''.join(items)); continue
        para.append(line.strip())
        i += 1
    flush_para()
    return '\n'.join(html)


def _donut_svg(rows, colors, size=170, stroke=26):
    """纯 SVG 环形图（无外部依赖）。rows: [(名称,数量), ...]"""
    import math as _m
    total = sum(v for _, v in rows) or 1
    r = (size - stroke) / 2
    c = 2 * _m.pi * r
    segs, acc = [], 0.0
    for name, v in rows:
        dash = v / total * c
        segs.append('<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" '
                    'stroke-width="%d" stroke-dasharray="%.2f %.2f" '
                    'stroke-dashoffset="%.2f" transform="rotate(-90 %.1f %.1f)"/>'
                    % (size / 2, size / 2, r, colors.get(name, '#94a3b8'), stroke,
                       dash, c - dash, -acc, size / 2, size / 2))
        acc += dash
    legend = ''.join('<span><span class="dot" style="background:%s"></span>%s %s（%.1f%%）</span>'
                     % (colors.get(name, '#94a3b8'), _esc(name), v, v / total * 100)
                     for name, v in rows)
    return ('<svg width="%d" height="%d" viewBox="0 0 %d %d">%s</svg>'
            '<div class="legend">%s</div>' % (size, size, size, size, ''.join(segs), legend))


def _bars_html(rows, unit=''):
    """横向条形图（纯 CSS）。rows: [(名称,数值), ...] 降序传入。"""
    if not rows:
        return '<p style="color:var(--muted)">（无数据）</p>'
    mx = max(v for _, v in rows) or 1
    out = []
    for name, v in rows:
        w = max(v / mx * 100, 1.5)
        out.append('<div class="bar-row"><div class="name" title="%s">%s</div>'
                   '<div class="track"><div class="fill" style="width:%.1f%%">%s</div></div>'
                   '<div class="val">%s%s</div></div>'
                   % (_esc(name), _esc(name), w, v if v / mx > .18 else '', v, unit))
    return ''.join(out)


def render_html(metrics, sections_by_cat):
    """渲染汇总 HTML（三类产物 + 总览图表，单文件）。sections_by_cat: {类别: {章节: html}}"""
    meta = metrics['meta']
    ov, ps = metrics['overview'], metrics['personnel']
    sc = metrics['summary_core']

    def fmt(v, suffix=''):
        return '-' if v is None else '%s%s' % (v, suffix)

    cards = [
        ('Bug总数', ov['bug_total'], ''),
        ('有效缺陷', ov['valid_total'], ''),
        ('解决率', fmt(ov['resolved_rate(%)'], '%'), ''),
        ('整体首过率', fmt(sc['first_pass_rate(%)'], '%'), 'plain'),
        ('整体回弹率', fmt(sc['bounce_rate(%)'], '%'), 'plain'),
        ('重复缺陷率', fmt(ov['duplicates']['rate(%)'], '%'), 'plain'),
        ('平均修复时长', fmt(sc['avg_fix_hours'], 'h'), 'plain'),
        ('平均验证时长', fmt(sc['avg_verify_hours'], 'h'), 'plain'),
    ]
    cards_html = ''.join('<div class="card"><div class="k">%s</div>'
                         '<div class="v %s">%s</div></div>'
                         % (_esc(k), cls, _esc(v)) for k, v, cls in cards)

    sev_rows = [(r['名称'], r['数量']) for r in ov['by_severity']]
    pri_rows = [(r['名称'], r['数量']) for r in ov['by_priority']]
    mod_rows = [(r['名称'], r['数量']) for r in ov['by_module'][:10]]
    lc_rows = [(k, v['平均(小时)'] or 0) for k, v in ps['lifecycle'].items()]

    missing_html = ''
    if metrics['missing']:
        missing_html = ('<div class="missing-box"><strong>缺失素材清单</strong><ul>%s</ul></div>'
                        % ''.join('<li>%s</li>' % _esc(x) for x in metrics['missing']))

    def sections_html(cat):
        secs = sections_by_cat.get(cat, {})
        if not secs:
            return '<div class="missing-box">未找到该类别的报告章节（请先执行 analyze）</div>'
        return '\n'.join('<h2 class="sec">%s</h2>%s' % (_esc(t), b)
                        for t, b in secs.items())

    panels = [('overview', '总览', True), ('dev', '开发侧', False),
              ('qa', '测试侧', False), ('product', '产品侧', False)]
    nav_html = ''.join('<button data-tab="%s"%s>%s</button>'
                       % (pid, ' class="active"' if act else '', _esc(label))
                       for pid, label, act in panels)

    overview_html = (
        cards_html + missing_html +
        '<div class="grid2">'
        '<div class="chart-card"><h3>严重程度分布</h3><div class="donut-wrap">%s</div></div>'
        '<div class="chart-card"><h3>业务优先级分布</h3>%s</div></div>'
        '<div class="chart-card"><h3>模块 Bug TOP10</h3>%s</div>'
        '<div class="chart-card"><h3>缺陷全生命周期平均耗时（小时）</h3>%s</div>'
        % (_donut_svg(sev_rows, _SEV_COLORS), _bars_html(pri_rows),
           _bars_html(mod_rows), _bars_html(lc_rows, 'h')))

    payload_json = json.dumps(metrics, ensure_ascii=False).replace('</', '<\\/')

    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{project} {version} 测试缺陷复盘报告</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>{project} {version} 测试缺陷复盘报告<span class="badge">{platform}</span></h1>
  <div class="meta">
    <span>生成时间：{generated}</span>
    <span>输入文件：{inputs}</span>
    <span>发布时间基准：{release}（口径：{rsource}）</span>
  </div>
</header>
<nav>{nav}</nav>
<main>
  <section class="panel active" id="tab-overview">{overview}</section>
  <section class="panel" id="tab-dev">{dev}</section>
  <section class="panel" id="tab-qa">{qa}</section>
  <section class="panel" id="tab-product">{product}</section>
</main>
<footer>由 test-defect-retrospective Skill 自动生成 ｜ 量化口径与全量数据见同目录
复盘数据_指标全量_*.json ｜ 本文件为自包含单文件，可直接离线打开与分享</footer>
<button id="toTop" title="返回顶部">&#8593;</button>
<script type="application/json" id="metrics-data">{payload}</script>
<script>
var btns=document.querySelectorAll('nav button');
btns.forEach(function(b){{b.onclick=function(){{
document.querySelectorAll('nav button').forEach(function(x){{x.classList.remove('active')}});
document.querySelectorAll('section.panel').forEach(function(p){{p.classList.remove('active')}});
b.classList.add('active');
var p=document.getElementById('tab-'+b.dataset.tab);if(p)p.classList.add('active');
window.scrollTo({{top:0}});
}};}});
var tt=document.getElementById('toTop');
window.onscroll=function(){{tt.style.display=window.scrollY>400?'block':'none';}};
tt.onclick=function(){{window.scrollTo({{top:0,behavior:'smooth'}});}};
</script>
</body>
</html>'''.format(css=_HTML_CSS, nav=nav_html, overview=overview_html,
                   dev=sections_html('开发'), qa=sections_html('测试'),
                   product=sections_html('产品'),
                   project=_esc(meta['project']), version=_esc(meta['version']),
                   platform=_esc(meta['platform'] or '-'),
                   generated=_esc(meta['generated_at']),
                   inputs=_esc('、'.join(meta['input_files']) or '-'),
                   release=_esc(meta['release_time'] or '未知'),
                   rsource=_esc(meta['release_time_source'] or '-'),
                   payload=payload_json)


def write_html(metrics, sections_by_cat, reports_dir):
    """输出汇总 HTML（时间戳幂等），返回文件路径。"""
    os.makedirs(reports_dir, exist_ok=True)
    path = _unique_path(os.path.join(reports_dir, '复盘报告_汇总_%s.html' % _ts()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_html(metrics, sections_by_cat))
    return path
