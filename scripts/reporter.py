# -*- coding: utf-8 -*-
"""报告生成模块：将指标全量数据渲染为固定的 3 大类产物（产品/开发/测试）。

规则：
- 章节结构与 SKILL.md 第四节完全一致，不得增减；
- 双格式输出：Markdown 可读报告 + JSON 结构化数据；
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

    tester_rows = [{'测试人员': t['测试人员'], '角色': t.get('角色', '-'),
                    '提交Bug数': t['提交Bug数'],
                    '个人占比(%)': t['个人占比(%)'],
                    '首次验证通过率(%)': t['首次验证通过率(%)'],
                    '驳回重修复率(%)': t['驳回重修复率(%)'],
                    '平均验证时长(小时)': t['平均验证时长(小时)'],
                    '重复上报Bug率(%)': t['重复上报Bug率(%)']} for t in ps['testers']]
    sec['一、测试人员提报效能全量指标'] = _table(tester_rows)

    sec['二、Bug验证通过率与驳回率统计'] = (
        _table(tester_rows) + '\n\n' + _ai_placeholder(
            '对各测试人员 titles_sample 标题采样做 Bug 描述语言风格分析与改良建议')
        if tester_rows else _missing_line('提报人字段'))

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
