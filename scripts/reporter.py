# -*- coding: utf-8 -*-
"""报告生成模块：渲染 3 大类产物（MD+JSON）与单文件汇总 HTML（工业质检档案风）。

规则：
- 章节结构与 SKILL.md 第四节完全一致，不得增减；
- 双格式输出：Markdown 可读报告 + JSON 结构化数据（+汇总 HTML，零外部依赖）；
- 文件名带时间戳，幂等运行不覆盖历史报告；
- 数据缺失的章节末尾统一标注：⚠️ 【数据缺失】缺少XX文件/字段，该项暂无法分析；
- AI 定性内容以「【AI分析】」占位标记预留，由 Skill 侧追加补充；
- 纯需求评审等单文档产物用 render_doc_html 渲染为档案风文档 HTML。
"""
import json
import os
import re
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
             '严重程度': i.get('severity'), '状态': i.get('status') or i.get('status_group'),
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
# 汇总 HTML 报告 —— 「工业质检档案」美学（单文件，零外部依赖，可离线分享）
# ---------------------------------------------------------------------------

_C = {'ink': '#1b1e22', 'line': '#23272b', 'hair': '#c9c2b2', 'paper': '#f4f0e6',
      'paper2': '#faf7ef', 'red': '#b3261e', 'dred': '#7f1d1d', 'amber': '#a66a08',
      'green': '#256b3a', 'navy': '#1f3a5f', 'gray': '#6b7280', 'lgray': '#9ca3af'}
SEV_COLORS = {'致命': _C['dred'], '严重': _C['red'], '一般': _C['amber'],
              '轻微': _C['gray'], '建议': _C['lgray'], '未分级': _C['lgray']}
PRI_COLORS = {'P0': _C['dred'], 'P1': _C['red'], 'P2': _C['amber'],
              'P3': _C['gray'], '未分级': _C['lgray']}

_NOISE = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' "
          "height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' "
          "baseFrequency='.9' numOctaves='2'/%3E%3CfeColorMatrix values='0 0 0 0 0 "
          "0 0 0 0 0 0 0 0 0 0 0 0 0 .05 0'/%3E%3C/filter%3E%3Crect width='140' "
          "height='140' filter='url(%23n)'/%3E%3C/svg%3E")

_HTML_CSS = """
:root{--paper:%(paper)s;--paper2:%(paper2)s;--ink:%(ink)s;--line:%(line)s;
--hair:%(hair)s;--red:%(red)s;--dred:%(dred)s;--amber:%(amber)s;--green:%(green)s;
--navy:%(navy)s;--gray:%(gray)s;--mark:#f3e7c3;
--serif:'Palatino Linotype','Book Antiqua','STZhongsong','SimSun',serif;
--sans:'Microsoft YaHei','PingFang SC',sans-serif;
--mono:'Consolas','SF Mono','Courier New',monospace;
--kai:'KaiTi','STKaiti','FangSong',serif}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--sans);color:var(--ink);background:#e6e0d0;
background-image:url("%(noise)s");line-height:1.65;font-size:13.5px}
.sheet{max-width:1180px;margin:26px auto 60px;background:var(--paper);
border:1.5px solid var(--line);box-shadow:6px 8px 0 rgba(27,30,34,.16);
position:relative;padding:0 34px 40px 56px}
.sheet::before{content:'';position:absolute;left:26px;top:0;bottom:0;width:1px;
background:repeating-linear-gradient(to bottom,transparent 0 26px,var(--hair) 26px 27px)}
.sheet::after{content:'';position:absolute;left:13px;top:0;bottom:0;width:14px;
background:radial-gradient(circle at 50%% 26px,#e6e0d0 4.2px,transparent 5px) repeat-y;
background-size:14px 52px;opacity:.9}
.masthead{border-bottom:4px double var(--line);padding:30px 0 18px;position:relative}
.masthead .over{font-family:var(--mono);font-size:10.5px;letter-spacing:.42em;
color:var(--navy);text-transform:uppercase}
.masthead h1{font-family:var(--serif);font-size:30px;font-weight:700;letter-spacing:.02em;
margin:10px 0 4px}
.masthead h1 small{display:block;font-size:15px;font-weight:400;color:var(--navy);
letter-spacing:.24em;margin-top:6px}
.doc-meta{display:flex;flex-wrap:wrap;gap:0 26px;margin-top:14px;font-size:12px;
font-family:var(--mono);color:#4a4f55;border-top:1px solid var(--hair);padding-top:10px}
.doc-meta b{color:var(--ink);font-weight:600}
.barcode{position:absolute;right:0;top:30px;text-align:right}
.barcode .bars{height:34px;width:150px;margin-left:auto;
background:repeating-linear-gradient(90deg,var(--ink) 0 2px,transparent 2px 4px,
var(--ink) 4px 7px,transparent 7px 9px,var(--ink) 9px 10px,transparent 10px 14px)}
.barcode .no{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;margin-top:3px}
.stamp{position:absolute;right:168px;top:34px;transform:rotate(7deg);
border:2.5px solid currentColor;border-radius:6px;padding:5px 12px;
font-family:var(--serif);font-weight:700;font-size:14.5px;letter-spacing:.3em;
opacity:.82;box-shadow:inset 0 0 0 1.5px var(--paper),inset 0 0 0 2.5px currentColor}
.index{position:sticky;top:0;z-index:9;display:flex;gap:4px;background:var(--paper);
border-bottom:1.5px solid var(--line);padding:10px 2px 0;overflow-x:auto}
.index button{font-family:var(--sans);font-size:13px;letter-spacing:.06em;cursor:pointer;
border:1.5px solid var(--line);border-bottom:0;background:var(--paper2);color:#5a5f66;
padding:7px 20px 6px;transform:translateY(1.5px);white-space:nowrap}
.index button .n{font-family:var(--mono);font-size:10px;display:block;letter-spacing:.3em;
color:var(--gray);margin-bottom:1px}
.index button.active{background:var(--ink);color:var(--paper);transform:translateY(0)}
.index button.active .n{color:var(--amber)}
.panel{display:none;padding-top:24px}
.panel.active{display:block}
.panel.active>*{animation:rise .45s cubic-bezier(.2,.7,.3,1) both}
.panel.active>*:nth-child(2){animation-delay:.06s}.panel.active>*:nth-child(3){animation-delay:.12s}
.panel.active>*:nth-child(4){animation-delay:.18s}.panel.active>*:nth-child(5){animation-delay:.24s}
.panel.active>*:nth-child(6){animation-delay:.3s}.panel.active>*:nth-child(7){animation-delay:.36s}
.panel.active>*:nth-child(8){animation-delay:.42s}.panel.active>*:nth-child(9){animation-delay:.48s}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.gauges{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:6px 0 18px}
@media(max-width:900px){.gauges{grid-template-columns:repeat(2,1fr)}}
.gauge{border:1.5px solid var(--line);background:var(--paper2);padding:10px 12px 12px;
position:relative;box-shadow:2px 3px 0 rgba(27,30,34,.1)}
.gauge .lab{font-family:var(--mono);font-size:10px;letter-spacing:.24em;color:var(--navy);
text-transform:uppercase;border-bottom:1px solid var(--hair);padding-bottom:5px;margin-bottom:7px}
.gauge .val{font-family:var(--mono);font-size:27px;font-weight:700;font-variant-numeric:tabular-nums;
line-height:1.1;letter-spacing:-.02em}
.gauge .val small{font-size:13px;font-weight:400;color:var(--gray);margin-left:2px}
.gauge .meter{height:5px;background:#e8e2d2;margin-top:8px;overflow:hidden}
.gauge .meter i{display:block;height:100%%;width:var(--w,0%%);animation:grow .9s .2s both}
@keyframes grow{from{width:0}}
.gauge.ok .val{color:var(--green)}.gauge.ok .meter i{background:var(--green)}
.gauge.warn .val{color:var(--amber)}.gauge.warn .meter i{background:var(--amber)}
.gauge.bad .val{color:var(--red)}.gauge.bad .meter i{background:var(--red)}
.gauge.flat .val{color:var(--ink)}.gauge.flat .meter i{background:var(--navy)}
.gauge .lamp{position:absolute;top:10px;right:11px;font-size:9px;letter-spacing:.14em;
font-family:var(--mono);color:var(--gray)}
.gauge.ok .lamp{color:var(--green);animation:breath 2.4s infinite}
.gauge.warn .lamp{color:var(--amber)}.gauge.bad .lamp{color:var(--red)}
@keyframes breath{50%%{opacity:.35}}
.block{border:1.5px solid var(--line);background:var(--paper2);margin:0 0 18px;
box-shadow:2px 3px 0 rgba(27,30,34,.1)}
.block>h3{font-family:var(--mono);font-size:11px;letter-spacing:.3em;color:var(--paper);
background:var(--navy);padding:6px 12px;text-transform:uppercase;display:flex;
justify-content:space-between}
.block>h3 em{font-style:normal;color:var(--amber);letter-spacing:.1em}
.block .bd{padding:14px 16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:880px){.grid2{grid-template-columns:1fr}}
.segbar{display:flex;height:36px;border:1.5px solid var(--line);overflow:hidden}
.segbar b{display:flex;align-items:center;justify-content:center;color:#fff;
font-family:var(--mono);font-size:12px;min-width:2px;position:relative;
animation:grow .8s both;white-space:nowrap;overflow:hidden}
.segbar b:nth-child(2){animation-delay:.1s}.segbar b:nth-child(3){animation-delay:.2s}
.segbar b:nth-child(4){animation-delay:.3s}.segbar b:nth-child(5){animation-delay:.4s}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:9px;font-size:12px;
font-family:var(--mono)}
.legend i{display:inline-block;width:9px;height:9px;margin-right:5px;vertical-align:-1px}
.pipe{display:flex;height:46px;border:1.5px solid var(--line);overflow:hidden}
.pipe b{display:flex;flex-direction:column;align-items:center;justify-content:center;
color:#fff;min-width:14%%;animation:grow .8s both;white-space:nowrap}
.pipe b span{font-size:10px;opacity:.85;letter-spacing:.2em}
.pipe b em{font-style:normal;font-family:var(--mono);font-size:14px;font-weight:700}
.pipe-sub{display:flex;justify-content:space-between;font-family:var(--mono);
font-size:10.5px;color:var(--gray);margin-top:6px}
.sec-head{display:flex;align-items:center;gap:12px;margin:34px 0 12px;
border-bottom:3px double var(--line);padding-bottom:8px;scroll-margin-top:70px}
.sec-head .no{flex:none;width:34px;height:34px;border:1.5px solid var(--line);
display:flex;align-items:center;justify-content:center;font-family:var(--serif);
font-size:17px;font-weight:700;background:var(--paper2);
box-shadow:inset 0 0 0 3px var(--paper2),inset 0 0 0 4px var(--hair)}
.sec-head h2{font-family:var(--serif);font-size:19px;font-weight:700;letter-spacing:.03em}
.sec-head .tag{margin-left:auto;font-family:var(--mono);font-size:10px;letter-spacing:.28em;
color:var(--gray)}
table{border-collapse:collapse;width:100%%;background:var(--paper2);font-size:12.5px;
margin:10px 0;border:1.5px solid var(--line)}
th{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em;text-align:left;
padding:8px 10px;border-bottom:3px double var(--line);background:var(--paper);
white-space:nowrap;color:var(--navy)}
td{padding:7px 10px;border-bottom:1px solid var(--hair);vertical-align:top;
font-variant-numeric:tabular-nums}
tbody tr:nth-child(even) td{background:rgba(31,58,95,.045)}
tbody tr{transition:transform .15s}
tbody tr:hover td{background:var(--mark);box-shadow:inset 3px 0 0 var(--amber)}
blockquote{background:var(--paper2);border:1px solid var(--hair);border-left:4px solid var(--red);
margin:12px 0;padding:11px 15px;font-size:12.5px;position:relative}
blockquote::before{content:'⚑ ATTENTION';display:block;font-family:var(--mono);
font-size:9.5px;letter-spacing:.3em;color:var(--red);margin-bottom:5px}
blockquote.ai{border-left-color:var(--green);transform:rotate(-.35deg);
font-family:var(--kai);font-size:13.5px}
blockquote.ai::before{content:'✎ 审核批注 · INSPECTOR NOTES';color:var(--green)}
.missing-box{border:1.5px solid var(--red);background:rgba(179,38,30,.05);padding:12px 16px;
margin:8px 0 18px;position:relative}
.missing-box>b{font-family:var(--mono);font-size:10.5px;letter-spacing:.3em;color:var(--red)}
.missing-box ul{margin:6px 0 0 20px;font-size:12.5px}
h3.sub{font-family:var(--serif);font-size:15px;margin:16px 0 6px;
border-left:3px solid var(--amber);padding-left:9px}
p{margin:8px 0}ul,ol{margin:8px 0 8px 22px}li{margin:3px 0}
strong{background:linear-gradient(transparent 62%%,var(--mark) 62%%);padding:0 1px}
code{font-family:var(--mono);background:#ece5d3;padding:0 4px;border:1px solid var(--hair)}
.colophon{margin-top:34px;border-top:4px double var(--line);padding-top:12px;
font-family:var(--mono);font-size:10.5px;letter-spacing:.14em;color:var(--gray);
display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
#toTop{position:fixed;right:26px;bottom:30px;width:42px;height:42px;border-radius:50%%;
border:1.5px solid var(--line);background:var(--paper2);color:var(--ink);font-size:15px;
cursor:pointer;box-shadow:3px 4px 0 rgba(27,30,34,.2);display:none;z-index:9}
#toTop:hover{background:var(--ink);color:var(--paper)}
@media print{body{background:#fff}.sheet{box-shadow:none;margin:0;max-width:none}
.index,#toTop{display:none}.panel{display:block!important;page-break-after:always}
.panel.active>*{animation:none}}
""" % {'paper': _C['paper'], 'paper2': _C['paper2'], 'ink': _C['ink'],
       'line': _C['line'], 'hair': _C['hair'], 'red': _C['red'], 'dred': _C['dred'],
       'amber': _C['amber'], 'green': _C['green'], 'navy': _C['navy'],
       'gray': _C['gray'], 'noise': _NOISE}


def _esc(s):
    return (str(s if s is not None else '').replace('&', '&amp;')
            .replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))


def _md_inline(s):
    """行内 Markdown → HTML（加粗=记号笔高亮；*斜体*）。"""
    s = _esc(s)
    parts = s.split('**')
    s = ''.join(p if i % 2 == 0 else '<strong>%s</strong>' % p
                for i, p in enumerate(parts))
    return re.sub(r'\*([^*\n]+)\*', r'<em>\1</em>', s)


def md_block_to_html(md):
    """轻量 Markdown → HTML（表格/引用/列表/标题/分割线/段落）。"""
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
        # 水平分割线 --- / ***
        if re.fullmatch(r'\s*([-*_])\s*(\1\s*){2,}', line):
            flush_para()
            html.append('<hr class="rule">')
            i += 1; continue
        if line.lstrip().startswith('|') and i + 1 < len(lines) and \
                set(lines[i + 1].replace('|', '').replace('-', '').strip()) <= set(': '):
            flush_para()
            headers = [c.strip() for c in line.strip().strip('|').split('|')]
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')])
                i += 1
            t = ['<table><thead><tr>'] + \
                ['<th>%s</th>' % _md_inline(h) for h in headers] + ['</tr></thead><tbody>']
            for r in rows:
                t.append('<tr>' + ''.join('<td>%s</td>' % _md_inline(c) for c in r) + '</tr>')
            t.append('</tbody></table>')
            html.append(''.join(t)); continue
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
        if line.lstrip().startswith('###'):
            flush_para()
            html.append('<h3 class="sub">%s</h3>' % _md_inline(line.lstrip()[3:].strip()))
            i += 1; continue
        if line.lstrip().startswith(('- ', '* ')):
            flush_para()
            items = []
            while i < len(lines) and lines[i].lstrip().startswith(('- ', '* ')):
                items.append('<li>%s</li>' % _md_inline(lines[i].lstrip()[2:]))
                i += 1
            html.append('<ul>%s</ul>' % ''.join(items)); continue
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


def _segbar_html(rows, colors, total=None):
    """分段能量条：rows=[(名称,数量)]，一段一色，段内标数。"""
    if not rows:
        return '<p style="font-family:var(--mono);color:var(--gray)">NO DATA</p>'
    total = total or (sum(v for _, v in rows) or 1)
    segs, legend = [], []
    for idx, (name, v) in enumerate(rows):
        w = v / total * 100
        color = colors.get(name, _C['gray'])
        label = '%d' % v if w > 6 else ''
        segs.append('<b style="width:%.2f%%;background:%s;animation-delay:%.1fs" '
                    'title="%s %d（%.1f%%）">%s</b>'
                    % (w, color, idx * 0.08, _esc(name), v, v / total * 100, label))
        legend.append('<span><i style="background:%s"></i>%s · %d（%.1f%%）</span>'
                      % (color, _esc(name), v, v / total * 100))
    return ('<div class="segbar">%s</div><div class="legend">%s</div>'
            % (''.join(segs), ''.join(legend)))


def _pareto_svg(rows, width=760, height=250):
    """帕累托图：柱（数量）+ 累计占比折线 + 80%% 参考线（纯 SVG）。"""
    if not rows:
        return '<p style="font-family:var(--mono);color:var(--gray)">NO DATA</p>'
    rows = rows[:8]
    n = len(rows)
    total = sum(v for _, v in rows) or 1
    l, r, t, b = 40, 46, 16, 40
    cw, ch = width - l - r, height - t - b
    mx = max(v for _, v in rows) or 1
    bw = cw / n * 0.62
    step = cw / n
    out = ['<svg viewBox="0 0 %d %d" style="width:100%%;height:auto;display:block">'
           % (width, height)]
    for gi in range(5):
        y = t + ch - ch * gi / 4
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" '
                   'stroke-width="1" stroke-dasharray="2 4" opacity=".55"/>'
                   % (l, y, l + cw, y, _C['hair']))
        out.append('<text x="%d" y="%.1f" font-family="Consolas,monospace" font-size="9" '
                   'fill="%s" text-anchor="end">%.0f</text>'
                   % (l - 5, y + 3, _C['gray'], mx * gi / 4))
    y80 = t + ch * 0.2
    out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="1" '
               'stroke-dasharray="5 3"/>' % (l, y80, l + cw, y80, _C['red']))
    out.append('<text x="%d" y="%.1f" font-family="Consolas,monospace" font-size="9" '
               'fill="%s" text-anchor="start">80%%</text>' % (l + cw + 6, y80 + 3, _C['red']))
    pts = []
    cum = 0
    for i, (name, v) in enumerate(rows):
        x = l + step * i + (step - bw) / 2
        h = ch * v / mx
        y = t + ch - h
        cum += v
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s">'
                   '<title>%s：%d（%.1f%%）</title></rect>'
                   % (x, y, bw, h, _C['navy'], _esc(name), v, v / total * 100))
        out.append('<text x="%.1f" y="%.1f" font-family="Consolas,monospace" font-size="9" '
                   'fill="%s" text-anchor="middle">%d</text>'
                   % (x + bw / 2, y - 4, _C['ink'], v))
        px = l + step * i + step / 2
        py = t + ch - ch * (cum / total)
        pts.append((px, py, cum))
        out.append('<circle cx="%.1f" cy="%.1f" r="3" fill="%s"/>' % (px, py, _C['red']))
    out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="1.8"/>'
               % (' '.join('%.1f,%.1f' % (px, py) for px, py, _ in pts), _C['red']))
    for px, py, cv in pts:
        out.append('<text x="%.1f" y="%.1f" font-family="Consolas,monospace" font-size="8.5" '
                   'fill="%s" text-anchor="middle">%.0f%%</text>'
                   % (px, py - 7, _C['red'], cv / total * 100))
    for i, (name, _) in enumerate(rows):
        nm = _esc(name if len(name) <= 8 else name[:7] + '…')
        x = l + step * i + step / 2
        out.append('<text x="%.1f" y="%d" font-size="10" fill="%s" text-anchor="middle" '
                   'transform="rotate(24 %.1f %d)">%s</text>'
                   % (x, height - 22, _C['ink'], x, height - 22, nm))
    out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1.5"/>'
               % (l, t + ch, l + cw, t + ch, _C['line']))
    out.append('</svg>')
    return ''.join(out)


def _pipe_html(lc):
    """生命周期管道：响应→修复→验证，段宽∝平均时长，色由浅入深。"""
    stages, total = [], 0.0
    for k, v in lc.items():
        h = v.get('平均(小时)') or 0
        total += h
        stages.append((k, h, v.get('样本数', 0)))
    if not stages or total <= 0:
        return '<p style="font-family:var(--mono);color:var(--gray)">NO DATA</p>'
    fills = ['#5b7ea3', '#3d5f85', _C['navy']]
    names = ['RESPONSE 响应', 'REPAIR 修复', 'VERIFY 验证']
    segs = []
    for i, (k, h, n) in enumerate(stages):
        w = h / total * 100
        segs.append('<b style="width:%.1f%%;background:%s;animation-delay:%.1fs">'
                    '<span>%s</span><em>%.1fh</em></b>'
                    % (w, fills[i % 3], i * 0.12, names[i % 3], h))
    sub = ''.join('<span>%s 样本 %s</span>' % (_esc(k), n) for k, h, n in stages)
    return '<div class="pipe">%s</div><div class="pipe-sub">%s</div>' % (
        ''.join(segs), sub)


def _lamp_class(v, ok_when, warn_when, higher_better=True):
    """按阈值给读数窗口定信号灯：ok/warn/bad/flat（None）。"""
    if v is None:
        return 'flat'
    if higher_better:
        if v >= ok_when:
            return 'ok'
        return 'warn' if v >= warn_when else 'bad'
    if v <= ok_when:
        return 'ok'
    return 'warn' if v <= warn_when else 'bad'


def render_html(metrics, sections_by_cat):
    """渲染汇总 HTML（工业质检档案风，单文件自包含）。"""
    meta = metrics['meta']
    ov, ps, sc = metrics['overview'], metrics['personnel'], metrics['summary_core']

    def g(label, en, v, suffix, ratio, lamp):
        lamp_txt = {'ok': '● PASS', 'warn': '● WATCH', 'bad': '● ALERT'}.get(lamp, '○ —')
        rv = '—' if v is None else v
        return ('<div class="gauge %s"><div class="lab">%s · %s</div>'
                '<div class="val"><span data-v="%s">%s</span><small>%s</small></div>'
                '<div class="meter"><i style="--w:%s%%"></i></div>'
                '<span class="lamp">%s</span></div>'
                % (lamp, _esc(label), en, rv, rv, suffix,
                   0 if ratio is None else max(0, min(100, ratio)), lamp_txt))

    gauges = ''.join([
        g('缺陷总数', 'TOTAL', ov['bug_total'], '条', None, 'flat'),
        g('有效缺陷', 'VALID', ov['valid_total'], '条', None, 'flat'),
        g('解决率', 'RESOLVED', ov['resolved_rate(%)'], '%',
          ov['resolved_rate(%)'], _lamp_class(ov['resolved_rate(%)'], 95, 80)),
        g('整体首过率', 'FIRST-PASS', sc['first_pass_rate(%)'], '%',
          sc['first_pass_rate(%)'], _lamp_class(sc['first_pass_rate(%)'], 90, 75)),
        g('整体回弹率', 'BOUNCE', sc['bounce_rate(%)'], '%',
          sc['bounce_rate(%)'], _lamp_class(sc['bounce_rate(%)'], 10, 20, False)),
        g('重复缺陷率', 'DUPLICATE', ov['duplicates']['rate(%)'], '%',
          ov['duplicates']['rate(%)'],
          _lamp_class(ov['duplicates']['rate(%)'], 5, 10, False)),
        g('平均修复', 'MTTR', sc['avg_fix_hours'], 'h',
          sc['avg_fix_hours'] and min(sc['avg_fix_hours'] / 72 * 100, 100),
          _lamp_class(sc['avg_fix_hours'], 24, 48, False)),
        g('平均验证', 'MTTV', sc['avg_verify_hours'], 'h',
          sc['avg_verify_hours'] and min(sc['avg_verify_hours'] / 72 * 100, 100),
          _lamp_class(sc['avg_verify_hours'], 24, 48, False)),
    ])

    sev_rows = [(r['名称'], r['数量']) for r in ov['by_severity']]
    pri_rows = [(r['名称'], r['数量']) for r in ov['by_priority']]
    mod_rows = [(r['名称'], r['数量']) for r in ov['by_module']]

    overview = (
        '<div class="gauges">%s</div>' % gauges +
        '<div class="block"><h3>PARETO · 模块缺陷帕累托<em>TOP %d</em></h3>'
        '<div class="bd">%s</div></div>'
        % (min(8, len(mod_rows)), _pareto_svg(mod_rows)) +
        '<div class="grid2">'
        '<div class="block"><h3>SEVERITY · 严重程度能量谱<em>%s</em></h3>'
        '<div class="bd">%s</div></div>'
        '<div class="block"><h3>PRIORITY · 业务优先级能量谱<em>%s</em></h3>'
        '<div class="bd">%s</div></div></div>'
        % (ov['valid_total'],
           ('<div class="missing-box"><b>⚠️ 严重程度字段未配置</b>'
            '<ul><li>缺陷导出无 severity 数据（100% 未分级），该项暂无法分析；'
            '建议 Jira 启用严重程度字段并在提报时必填</li></ul></div>'
            if (not sev_rows or all(n == '未分级' for n, _ in sev_rows))
            else _segbar_html(sev_rows, SEV_COLORS)),
           ov['valid_total'], _segbar_html(pri_rows, PRI_COLORS)) +
        '<div class="block"><h3>LIFECYCLE · 全生命周期管道<em>响应→修复→验证</em></h3>'
        '<div class="bd">%s</div></div>' % _pipe_html(ps['lifecycle']))

    if metrics['missing']:
        overview += ('<div class="missing-box"><b>EXHIBIT · 缺失素材清单</b><ul>%s</ul></div>'
                     % ''.join('<li>%s</li>' % _esc(x) for x in metrics['missing']))

    def sections_html(cat, en):
        secs = sections_by_cat.get(cat, {})
        if not secs:
            return '<div class="missing-box"><b>未找到该类别报告章节</b>' \
                   '<ul><li>请先执行 analyze</li></ul></div>'
        out = []
        for title, body in secs.items():
            m = re.match(r'^([一二三四五六七八九十]+)、(.*)$', title)
            no, txt = (m.group(1), m.group(2)) if m else ('§', title)
            out.append('<div class="sec-head"><span class="no">%s</span><h2>%s</h2>'
                       '<span class="tag">%s</span></div>%s'
                       % (no, _esc(txt), en, body))
        return '\n'.join(out)

    panels = [('overview', 'OVERVIEW', '总览', True),
              ('dev', 'DEV', '开发侧', False),
              ('qa', 'QA', '测试侧', False),
              ('product', 'PRODUCT', '产品侧', False)]
    nav = ''.join('<button data-tab="%s"%s><span class="n">%s</span>%s</button>'
                  % (pid, ' class="active"' if act else '', en, _esc(label))
                  for pid, en, label, act in panels)

    unclosed = ov['valid_total'] - ov['closed_total']
    if unclosed == 0:
        stamp = ('<div class="stamp" style="color:%s">缺陷全闭环</div>' % _C['green'])
    else:
        stamp = ('<div class="stamp" style="color:%s">%d 条未闭环</div>'
                 % (_C['red'], unclosed))
    arch_no = 'TDR-' + re.sub(r'[^0-9]', '', meta['generated_at'])

    payload = json.dumps(metrics, ensure_ascii=False).replace('</', '<\\/')

    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(project)s %(version)s 测试缺陷复盘检验档案</title>
<style>%(css)s</style>
</head>
<body>
<div class="sheet">
  <header class="masthead">
    <div class="over">QA INSPECTION DOSSIER · 检验档案 · 仅限内部流传</div>
    <h1>%(project)s <span style="font-family:var(--mono);font-size:24px">%(version)s</span>
    测试缺陷复盘检验报告<small>TEST DEFECT RETROSPECTIVE INSPECTION SHEET</small></h1>
    <div class="doc-meta">
      <span>平台 <b>%(platform)s</b></span>
      <span>建档 <b>%(generated)s</b></span>
      <span>输入 <b>%(inputs)s</b></span>
      <span>基准 <b>%(release)s</b>（%(rsource)s）</span>
    </div>
    <div class="barcode"><div class="bars"></div><div class="no">%(arch)s</div></div>
    %(stamp)s
  </header>
  <nav class="index">%(nav)s</nav>
  <main>
    <section class="panel active" id="tab-overview">%(overview)s</section>
    <section class="panel" id="tab-dev">%(dev)s</section>
    <section class="panel" id="tab-qa">%(qa)s</section>
    <section class="panel" id="tab-product">%(product)s</section>
  </main>
  <footer class="colophon">
    <span>ISSUED BY test-defect-retrospective SKILL</span>
    <span>口径与全量数据 → 复盘数据_指标全量_*.json</span>
    <span>自包含单文件 · 可离线查阅与转递</span>
  </footer>
</div>
<button id="toTop" title="返回顶部">▲</button>
<script type="application/json" id="metrics-data">%(payload)s</script>
<script>
var bs=document.querySelectorAll('.index button');
/* 读数窗口数字滚动 */
function countUp(el){var t=parseFloat(el.getAttribute('data-v'));
if(isNaN(t)){el.textContent=el.getAttribute('data-v');return;}
var dec=(String(el.getAttribute('data-v')).split('.')[1]||'').length;
var st=performance.now();function f(now){var p=Math.min((now-st)/900,1);
p=1-Math.pow(1-p,3);el.textContent=(t*p).toFixed(dec);
if(p<1)requestAnimationFrame(f);}requestAnimationFrame(f);}
/* Tab 切换：切换面板并触发数字滚动。
   注意 onclick 为属性赋值，重复赋值会互相覆盖，必须合并为单一处理器 */
function showTab(b){
document.querySelectorAll('.index button').forEach(function(x){x.classList.remove('active')});
document.querySelectorAll('.panel').forEach(function(p){p.classList.remove('active')});
b.classList.add('active');
var p=document.getElementById('tab-'+b.dataset.tab);
if(p){p.classList.add('active');
setTimeout(function(){p.querySelectorAll('.val span[data-v]').forEach(countUp);},30);}
window.scrollTo({top:0});}
bs.forEach(function(b){b.onclick=function(){showTab(b);};});
document.querySelectorAll('.panel.active .val span[data-v]').forEach(countUp);
var tt=document.getElementById('toTop');
window.onscroll=function(){tt.style.display=window.scrollY>420?'block':'none';};
tt.onclick=function(){window.scrollTo({top:0,behavior:'smooth'});};
</script>
</body>
</html>''' % {'css': _HTML_CSS, 'nav': nav, 'overview': overview,
               'dev': sections_html('开发', 'DEV REPORT'),
               'qa': sections_html('测试', 'QA REPORT'),
               'product': sections_html('产品', 'PRODUCT REPORT'),
               'project': _esc(meta['project']), 'version': _esc(meta['version']),
               'platform': _esc(meta['platform'] or '-'),
               'generated': _esc(meta['generated_at']),
               'inputs': _esc('、'.join(meta['input_files']) or '-'),
               'release': _esc(meta['release_time'] or '未知'),
               'rsource': _esc(meta['release_time_source'] or '-'),
               'arch': arch_no, 'stamp': stamp, 'payload': payload}


def write_html(metrics, sections_by_cat, reports_dir):
    """输出汇总 HTML（时间戳幂等），返回文件路径。"""
    os.makedirs(reports_dir, exist_ok=True)
    path = _unique_path(os.path.join(reports_dir, '复盘报告_汇总_%s.html' % _ts()))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_html(metrics, sections_by_cat))
    return path


# ---------------------------------------------------------------------------
# 文档式 HTML（纯需求评审等单文档产物的「质检档案」渲染，无指标依赖）
# ---------------------------------------------------------------------------

def render_doc_html(md_text, stamp='需求评审', stamp_color=None):
    """将单份 Markdown 报告渲染为档案风 HTML：
    首行「# 标题」→ 大标题；开头连续「> 」行 → 档案元信息；其余按章节渲染。"""
    lines = md_text.split('\n')
    title, meta_lines, body_start = '', [], 0
    for idx, ln in enumerate(lines):
        s = ln.strip()
        if idx == 0 and s.startswith('# '):
            title = s[2:].strip()
            body_start = idx + 1
            continue
        if idx >= body_start and s.startswith('>'):
            meta_lines.append(s.lstrip('> ').strip())
            body_start = idx + 1
        elif idx >= body_start and not s:
            continue
        else:
            break
    body = '\n'.join(lines[body_start:])

    # 章节化：## 标题 → 方章章节头
    out, sec_no = [], 0
    for part in body.split('\n## '):
        if not part.strip():
            continue
        chunk = part.split('\n', 1)
        head = chunk[0].strip()
        rest = chunk[1] if len(chunk) > 1 else ''
        m = re.match(r'^([一二三四五六七八九十]+)、(.*)$', head)
        if m or (out and not head.startswith('#')):
            sec_no += 1
            no = m.group(1) if m else str(sec_no)
            txt = m.group(2) if m else head
            out.append('<div class="sec-head"><span class="no">%s</span><h2>%s</h2>'
                       '<span class="tag">DOC REPORT</span></div>%s'
                       % (no, _esc(txt), md_block_to_html(rest)))
        else:
            out.append(md_block_to_html(part))
    content = '\n'.join(out)

    stamp_html = ('<div class="stamp" style="color:%s">%s</div>'
                  % (stamp_color or _C['navy'], _esc(stamp)))
    arch_no = 'TDR-' + time.strftime('%Y%m%d%H%M%S')
    meta_html = ''.join('<span>%s</span>' % _esc(x) for x in meta_lines if x)
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>%(title)s</title>
<style>%(css)s
hr.rule{border:0;border-top:3px double var(--line);margin:22px 0}
.doc-meta span{display:block}
</style>
</head>
<body>
<div class="sheet">
  <header class="masthead">
    <div class="over">QA DOSSIER · 检验档案 · 仅限内部流传</div>
    <h1>%(title)s<small>DOCUMENT REVIEW SHEET</small></h1>
    <div class="doc-meta">%(meta)s</div>
    <div class="barcode"><div class="bars"></div><div class="no">%(arch)s</div></div>
    %(stamp)s
  </header>
  <main style="padding-top:6px">%(content)s</main>
  <footer class="colophon">
    <span>ISSUED BY test-defect-retrospective SKILL</span>
    <span>自包含单文件 · 可离线查阅与转递</span>
  </footer>
</div>
<button id="toTop" title="返回顶部">▲</button>
<script>
var tt=document.getElementById('toTop');
window.onscroll=function(){tt.style.display=window.scrollY>420?'block':'none';};
tt.onclick=function(){window.scrollTo({top:0,behavior:'smooth'});};
</script>
</body>
</html>''' % {'title': _esc(title or '文档评审'), 'css': _HTML_CSS,
               'meta': meta_html, 'arch': arch_no, 'stamp': stamp_html,
               'content': content}


def write_doc_html(md_path, reports_dir, stamp='需求评审', stamp_color=None):
    """读取 Markdown 报告并输出档案风 HTML（时间戳幂等），返回文件路径。"""
    os.makedirs(reports_dir, exist_ok=True)
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
    base = re.sub(r'\.md$', '', os.path.basename(md_path))
    if not re.search(r'_\d{8}(_\d{6})?$', base):   # 已含时间戳则不重复追加
        base = '%s_%s' % (base, _ts())
    path = _unique_path(os.path.join(reports_dir, base + '.html'))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_doc_html(md_text, stamp=stamp, stamp_color=stamp_color))
    return path
