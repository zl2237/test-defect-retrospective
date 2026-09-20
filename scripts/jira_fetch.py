#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Jira PAT 拉取器：按 sprint / JQL 导出缺陷主表 + 活动日志 + 评论，输出为本 skill 标准输入格式。

背景：手工导出/JQL 界面导出常缺严重程度、解决结果、分配/关闭时间、重开次数等字段，
导致复盘指标（严重度分布、有效缺陷、验证时长、回弹率等）失真。本脚本通过
/rest/api/2/search?expand=changelog 一次拉齐，并从 changelog 派生缺失字段。

用法（PAT 即 Jira「个人访问令牌」，亦可由环境变量 JIRA_PAT 提供）：
  python scripts/jira_fetch.py --base http://jira.example.com --project WLXT --sprint 21 --out "{项目名}/{版本号}/defects"
  python scripts/jira_fetch.py --base http://jira.example.com --jql "project = WLXT AND fixVersion = v1.5.0" --out defects

产出（均为 utf-8-sig CSV）：
  <out>/缺陷主表.csv           含 key/标题/状态/严重程度/优先级/所属模块/报告人/经办人/解决人/
                              验证人/创建时间/分配时间/解决时间/关闭时间/解决结果/重开次数/
                              标签/关联需求/复现概率/备注（未配置的列输出为空，报告按缺失标注）
  <out>/明细/改动记录明细.csv   活动日志（放子目录，_list_input_files 非递归，不会被 parse 误当缺陷表）
  <out>/明细/评论明细.csv       评论明细
  <out>/../人员角色_模板.csv    按本次数据中实际出现的人员生成（姓名,角色待填；填好后改名
                              「人员角色.csv」放版本根目录）

说明：
- 仅标准库（urllib），无 requests/openpyxl 依赖；只读 GET，不修改 Jira 数据。
- 状态归组使用 statusCategory（new/indeterminate/done）优先，中文状态名兜底，口径对齐 normalize.py。
- 重开次数 = changelog 中状态从「已解决/已关闭/验证中类」回退到「打开/处理中/待确认类」的次数
  （覆盖常见工作流「验证中→待确认」的测试打回形态）。
- 自定义字段：--severity-field / --root-cause-field 可指定 customfield_XXX 键名。
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- 状态归组（与 normalize.py 口径对齐）

_DONE_WORDS = {'已关闭', '关闭', '已完成', '已完结', '已验证', '已验证通过', '已验收',
               'closed', 'done', 'verified'}
_RESOLVED_WORDS = {'已解决', '解决', '已修复', '修复完成', '待验证', '待测试验证', '验证中',
                   'resolved', 'fixed', 'ready for qa', 'in qa'}
_OPEN_WORDS = {'打开', '待办', '新建', '激活', '待处理', '未处理', '待指派', '待确认', '重新打开', '重开',
               'open', 'to do', 'todo', 'backlog', 'new', 'created', 'active', 'reopened'}
_IN_PROGRESS_WORDS = {'处理中', '进行中', '开发中', '修复中',
                      'in progress', 'processing', 'investigating'}


def _norm(s):
    return re.sub(r'\s+', '', str(s or '')).lower()


def status_bucket(name, category_key=None):
    """状态 → open / in_progress / resolved / closed（statusCategory 优先，名称兜底）。"""
    if category_key == 'done':
        return 'closed'
    if category_key == 'new':
        return 'open'
    v = _norm(name)
    if not v:
        return None
    for w in _DONE_WORDS:
        if _norm(w) == v:
            return 'closed'
    for w in _RESOLVED_WORDS:
        if _norm(w) == v:
            return 'resolved'
    for w in _IN_PROGRESS_WORDS:
        if _norm(w) == v:
            return 'in_progress'
    for w in _OPEN_WORDS:
        if _norm(w) == v:
            return 'open'
    for w in ('已关闭', 'closed', 'done'):      # 包含匹配（如「已关闭(Closed)」）
        if w in v:
            return 'closed'
    for w in ('已解决', 'resolved', 'fixed', '待验证'):
        if w in v:
            return 'resolved'
    return None


# ---------------------------------------------------------------- HTTP（仅标准库）

def _get_json(base, path, params, headers, retries=2):
    url = base.rstrip('/') + path + '?' + urllib.parse.urlencode(params)
    last_err = None
    for _ in range(retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', 'ignore')[:300]
            except Exception:
                pass
            if e.code in (401, 403):
                raise SystemExit('认证失败(%s)：请检查 --pat / JIRA_PAT 令牌是否有效。%s' % (e.code, body))
            if e.code < 500:
                raise SystemExit('请求失败(%s)：%s %s' % (e.code, url, body))
            last_err = e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
    raise SystemExit('请求多次失败：%s（%s）' % (url, last_err))


def fetch_issues(base, jql, headers):
    start, total = 0, 1
    while start < total:
        data = _get_json(base, '/rest/api/2/search', {
            'jql': jql, 'startAt': start, 'maxResults': 100,
            'fields': '*all', 'expand': 'changelog',
        }, headers)
        total = int(data.get('total', 0))
        for iss in data.get('issues', []):
            yield iss
        start += 100


def search_with_types(base, headers, project, sprint, types, args_jql):
    """执行搜索，返回 (issues, jql)。JQL 默认按 issuetype 过滤，
    若实例缺少某类型（400「域中没有"X"值」）则自动剔除该类型后重试。"""
    if args_jql:
        return list(fetch_issues(base, args_jql, headers)), args_jql
    types = [t.strip() for t in types.split(',') if t.strip()]
    while True:
        # 数字 sprint 为内部 ID，需不加引号；名称则加引号
        sprint_cond = sprint if str(sprint).isdigit() else '"%s"' % sprint
        jql = 'project = %s AND issuetype in (%s) AND sprint = %s' % (
            project, ', '.join('"%s"' % t for t in types), sprint_cond)
        try:
            return list(fetch_issues(base, jql, headers)), jql
        except SystemExit as e:
            missing = re.findall(r'没有["“]([^"”]+)["”]值', str(e))
            if missing and any(m in types for m in missing):
                types = [t for t in types if t not in missing]
                if types:
                    print('[提示] 实例缺少类型 %s，已自动剔除，剩余：%s' % (missing, types))
                    continue
            raise


# ---------------------------------------------------------------- 字段抽取与派生

def uname(d):
    return (d or {}).get('displayName') or (d or {}).get('name') or ''


def histories(iss):
    return iss.get('changelog', {}).get('histories', [])


def derive_from_changelog(iss):
    """从 changelog 派生：分配时间 / 解决人 / 关闭时间 / 关闭人(验证人) / 重开次数。"""
    assigned_at = resolver = closed_at = verifier = resolved_at = None
    reopen_count = 0
    prev_bucket = None
    for h in sorted(histories(iss), key=lambda x: x.get('created', '')):
        ts, author = h.get('created'), uname(h.get('author'))
        for it in h.get('items', []):
            field = (it.get('field') or '').lower()
            if field == 'assignee' and not assigned_at and it.get('to'):
                assigned_at = ts                       # 首次分配时间
            if field == 'status':
                to_b = status_bucket(it.get('toString'))
                if to_b in ('resolved', 'closed') and resolver is None:
                    resolver = author                  # 首次解决人
                    resolved_at = ts                   # 首次进入已解决/关闭类的时间
                if to_b == 'closed':
                    closed_at, verifier = ts, author   # 最后一次关闭（人/时间）
                # 回退：已解决/关闭 → 打开/处理中 记一次重开
                if prev_bucket in ('resolved', 'closed') and to_b in ('open', 'in_progress'):
                    reopen_count += 1
                prev_bucket = to_b
    return {'assigned_at': assigned_at, 'resolver': resolver, 'resolved_at': resolved_at,
            'closed_at': closed_at, 'verifier': verifier, 'reopen_count': reopen_count}


def linked_requirements(f):
    keys = []
    for ln in f.get('issuelinks', []) or []:
        for side in ('inwardIssue', 'outwardIssue'):
            if ln.get(side):
                keys.append(ln[side].get('key'))
    return '; '.join(dict.fromkeys(k for k in keys if k))


def build_rows(issues, args):
    main_rows, change_rows, comment_rows = [], [], []
    people = set()

    for iss in issues:
        f = iss.get('fields', {}) or {}
        der = derive_from_changelog(iss)

        for h in histories(iss):
            for it in h.get('items', []):
                change_rows.append({
                    'key': iss.get('key'), '标题': f.get('summary'),
                    '改动时间': h.get('created'), '操作人': uname(h.get('author')),
                    '改的字段': it.get('field'),
                    '原值': it.get('fromString', ''), '新值': it.get('toString', ''),
                })
        for c in (f.get('comment', {}) or {}).get('comments', []):
            comment_rows.append({
                'key': iss.get('key'), '标题': f.get('summary'),
                '评论时间': c.get('created'), '评论人': uname(c.get('author')),
                '评论内容': c.get('body', ''),
            })

        severity = ''
        if args.severity_field:
            v = f.get(args.severity_field)
            severity = (v.get('name') or v.get('value')) if isinstance(v, dict) else (v or '')
        elif isinstance(f.get('severity'), dict):
            severity = f['severity'].get('name', '')
        root_cause = ''
        if args.root_cause_field:
            v = f.get(args.root_cause_field)
            root_cause = ((v.get('value') or v.get('name')) if isinstance(v, dict) else (v or ''))

        main_rows.append({
            'key': iss.get('key'),
            '标题': f.get('summary'),
            '状态': (f.get('status', {}) or {}).get('name', ''),
            '严重程度': severity,
            '优先级': (f.get('priority', {}) or {}).get('name', ''),
            '所属模块': ', '.join(c.get('name', '') for c in f.get('components', []) or []),
            '报告人': uname(f.get('reporter')),
            '经办人': uname(f.get('assignee')),
            '解决人': der['resolver'] or uname(f.get('assignee')),
            '验证人': der['verifier'] or uname(f.get('reporter')),
            '创建时间': f.get('created'),
            '分配时间': der['assigned_at'],
            '解决时间': f.get('resolutiondate') or der['resolved_at'],
            '关闭时间': der['closed_at'],
            '解决结果': (f.get('resolution', {}) or {}).get('name', ''),
            '重开次数': der['reopen_count'],
            '标签': '; '.join(f.get('labels', []) or []),
            '关联需求': linked_requirements(f),
            '复现概率': '',
            '备注': re.sub(r'[ \t]+\n', '\n', (f.get('description') or '')).strip(),
        })
        people.update(main_rows[-1][k] for k in ('报告人', '经办人', '解决人', '验证人'))

    return main_rows, change_rows, comment_rows, sorted(p for p in people if p)


def write_csv(path, fieldnames, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(
        description='Jira PAT 缺陷拉取（主表+活动日志+评论 → skill 标准输入）')
    ap.add_argument('--base', required=True, help='Jira 地址，如 http://192.168.22.110:8080')
    ap.add_argument('--pat', default=os.environ.get('JIRA_PAT'),
                    help='个人访问令牌（缺省读环境变量 JIRA_PAT）')
    ap.add_argument('--project', help='项目 KEY，如 WLXT（与 --sprint 组合使用）')
    ap.add_argument('--sprint', help='sprint 编号或名称，如 21')
    ap.add_argument('--jql', help='自定义 JQL（优先于 --project/--sprint）')
    ap.add_argument('--types', default='缺陷,阻塞,Bug', help='issuetype 过滤（默认：缺陷,阻塞,Bug；实例缺少的类型会自动剔除重试）')
    ap.add_argument('--out', required=True, help='输出目录（即 {项目名}/{版本号}/defects）')
    ap.add_argument('--severity-field', help='严重程度自定义字段键名（如 customfield_10001）')
    ap.add_argument('--root-cause-field', help='根因自定义字段键名')
    args = ap.parse_args()

    if not args.pat:
        raise SystemExit('缺少 PAT：请传 --pat 或设置环境变量 JIRA_PAT')
    if not args.jql and not (args.project and args.sprint):
        raise SystemExit('请提供 --jql，或同时提供 --project 与 --sprint')

    headers = {'Authorization': 'Bearer %s' % args.pat, 'Accept': 'application/json'}
    issues, jql = search_with_types(args.base, headers, args.project, args.sprint,
                                    args.types, args.jql)
    main_rows, change_rows, comment_rows, people = build_rows(issues, args)

    out = args.out.rstrip('/\\')
    write_csv(os.path.join(out, '缺陷主表.csv'),
              list(main_rows[0].keys()) if main_rows else ['key', '标题', '状态'], main_rows)
    write_csv(os.path.join(out, '明细', '改动记录明细.csv'),
              ['key', '标题', '改动时间', '操作人', '改的字段', '原值', '新值'], change_rows)
    write_csv(os.path.join(out, '明细', '评论明细.csv'),
              ['key', '标题', '评论时间', '评论人', '评论内容'], comment_rows)
    # 人员角色模板：写到版本根目录（defects 的上一级）
    role_path = os.path.join(os.path.dirname(os.path.abspath(out)), '人员角色_模板.csv')
    write_csv(role_path, ['姓名', '角色'],
              [{'姓名': p, '角色': '待填（前端/后端/产品/测试）'} for p in people])

    print('导出完成（JQL：%s）' % jql)
    print('缺陷主表：%d 条 ｜ 改动记录：%d 条 ｜ 评论：%d 条 ｜ 人员：%d 人' % (
        len(main_rows), len(change_rows), len(comment_rows), len(people)))
    print('主表字段缺口自查：严重程度有值 %d 条、解决结果有值 %d 条、关闭时间有值 %d 条、重开>0 共 %d 条' % (
        sum(1 for r in main_rows if r['严重程度']),
        sum(1 for r in main_rows if r['解决结果']),
        sum(1 for r in main_rows if r['关闭时间']),
        sum(1 for r in main_rows if r['重开次数'])))
    print('请编辑并改名「%s」→ 人员角色.csv（同目录）后，角色口径即可生效' % role_path)


if __name__ == '__main__':
    main()
