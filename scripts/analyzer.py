# -*- coding: utf-8 -*-
"""指标计算模块：基于统一标准中间数据集计算全量量化指标。

设计原则：
1. 同输入必同输出 —— 全部指标为确定性计算，无随机因素；
2. 数据缺失不阻塞 —— 可算则算，不可算输出 None/空列表并登记缺失项；
3. 禁止编造 —— 缺失字段一律 None/空，不做推测填充。
口径与 SKILL.md 第三节保持一致，修改口径需两处同步。
"""
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime

import normalize as nz
from parsers.base import read_table, norm_header

# ---------------------------------------------------------------------------
# 测试用例表头映射（test_cases/ 目录文件）
# ---------------------------------------------------------------------------
TC_FIELD_MAP = {
    'case_id': ['用例编号', '编号', 'ID', 'Case ID', '用例ID'],
    'title': ['用例标题', '标题', '名称', '用例名称', 'Case'],
    'module': ['所属模块', '模块', '功能模块', '一级模块', '系统模块'],
    'requirement_id': ['关联需求', '需求ID', '需求编号', '关联需求ID', 'Story', '需求'],
    'status': ['执行状态', '执行结果', '结果', '状态', '最近执行结果', '测试结果'],
    'priority': ['优先级', '级别', 'Priority'],
    'is_regression': ['是否回归', '回归', '回归用例', '用例类型'],
    'duration_min': ['执行时长', '执行时长(分钟)', '耗时', '耗时(分钟)', '执行时长（分钟）'],
    'block_reason': ['阻塞原因', '失败原因', '备注', '备注说明'],
}
TC_STATUS_GROUPS = [
    ('通过', ['通过', 'pass', 'passed', '成功', 'ok']),
    ('失败', ['失败', 'fail', 'failed', '不通过', 'bug']),
    ('阻塞', ['阻塞', 'block', 'blocked', '锁定']),
    ('跳过', ['跳过', 'skip', 'skipped', '忽略', '不执行']),
    ('未执行', ['未执行', 'not run', 'notrun', '待执行', '未跑']),
]
# 阻塞原因分类（关键词规则）
BLOCK_REASON_RULES = [
    ('环境问题', ['环境', '服务器', '部署', '数据库', '中间件', '配置']),
    ('提测延期', ['延期', '延迟', '未提测', '提测', '未交付', '未发版']),
    ('依赖阻塞', ['依赖', '上游', '下游', '第三方', '联调', '等待']),
    ('数据问题', ['数据', '账号', '造数', '测试数据']),
]

# 漏测风险关键词（高风险场景扫描）
RISK_KEYWORDS = {
    '边界场景': ['边界', '极限', '最大值', '最小值', '临界', '溢出'],
    '并发场景': ['并发', '同时', '竞态', '多用户', '秒杀', '抢购'],
    '大数据量场景': ['大数据', '大量', '批量', '海量', '分页', '性能'],
    '弱网场景': ['弱网', '断网', '超时', '重试', '网络切换', '离线'],
}
# 需求侧/联调类关键词
URGENT_KEYWORDS = ['加急', '临时', '紧急插入', '插需']
DEPENDENCY_KEYWORDS = ['联调', '依赖', '上游', '下游', '接口对接', '第三方对接']

# 生命周期耗时分桶（小时）
HOUR_BUCKETS = [('＜4小时', 0, 4), ('4-24小时', 4, 24), ('1-3天', 24, 72), ('＞3天', 72, float('inf'))]

SEVERITY_ORDER = ['致命', '严重', '一般', '轻微', '建议', '未分级']


def _pct(a, b):
    """百分比（保留2位小数）；分母为0返回 None。"""
    return round(a / b * 100, 2) if b else None


def _mean_hours(pairs):
    """[(结束,开始)] 平均小时数（剔除负值/缺失），保留1位小数。"""
    hours = [(e - s).total_seconds() / 3600
             for e, s in pairs if e and s and (e - s).total_seconds() >= 0]
    return round(sum(hours) / len(hours), 1) if hours else None


def _bucket(hours):
    for name, lo, hi in HOUR_BUCKETS:
        if hours is not None and lo <= hours < hi:
            return name
    return '未知'


def _group_counts(items, key, order=None):
    """按字段分组统计 数量+占比。"""
    counter = defaultdict(int)
    for it in items:
        counter[it.get(key) or '未知'] += 1
    total = len(items)
    rows = [{'名称': k, '数量': v, '占比(%)': _pct(v, total)}
            for k, v in counter.items()]
    if order:
        rows.sort(key=lambda r: (order.index(r['名称']) if r['名称'] in order else 99,
                                 -r['数量']))
    else:
        rows.sort(key=lambda r: -r['数量'])
    return rows


def _dt_iso(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None


def _bug_brief(b):
    """缺陷摘要行（用于清单输出，时间转ISO）。"""
    return {
        'bug_id': b.get('bug_id') or ('%s#%s' % (b.get('_source_file', ''), b.get('_source_row', ''))),
        'title': b.get('title'),
        'module': b.get('module') or '未知',
        'severity': b.get('severity_std'),
        'status': b.get('status'),
        'status_group': b.get('status_group'),
        'reporter': b.get('reporter'),
        'assignee': b.get('assignee'),
        'resolver': b.get('resolver') or b.get('assignee'),
        'created_at': _dt_iso(b.get('created_at_dt')),
        'resolved_at': _dt_iso(b.get('resolved_at_dt')),
        'closed_at': _dt_iso(b.get('closed_at_dt')),
        'root_cause': b.get('root_cause_std'),
        'reopen_count': b.get('reopen_count', 0),
    }


# ---------------------------------------------------------------------------
# 测试用例解析（CSV / Excel / XMind）
# ---------------------------------------------------------------------------

def _tc_status_std(raw):
    if raw is None or not str(raw).strip():
        return '未执行'
    v = nz._norm(raw)
    for std, aliases in TC_STATUS_GROUPS:
        if v in [nz._norm(a) for a in aliases]:
            return std
    for std, aliases in TC_STATUS_GROUPS:
        for a in aliases:
            if nz._norm(a) and nz._norm(a) in v:
                return std
    return '未执行'


# XMind 优先级图标 → 标准优先级（priority-1 最高）
_XMIND_PRI = {'priority-1': 'P0', 'priority-2': 'P1', 'priority-3': 'P2',
              'priority-4': 'P3', 'priority-5': 'P3', 'priority-6': 'P3'}


def _xmind_priority_zen(topic):
    """XMind Zen/2020+（content.json）主题的优先级标记。"""
    for mk in topic.get('markers') or []:
        mid = str(mk.get('markerId') or mk.get('id') or '')
        if mid in _XMIND_PRI:
            return _XMIND_PRI[mid]
    return None


def _xmind_tree_zen(topic):
    """XMind Zen JSON 主题 → 统一树节点 {title, priority, children}。"""
    return {
        'title': str(topic.get('title') or '').strip(),
        'priority': _xmind_priority_zen(topic),
        'children': [_xmind_tree_zen(c)
                     for c in (topic.get('children') or {}).get('attached') or []],
    }


def _xmind_tree_xml(xml_text):
    """XMind 8（content.xml）→ 统一树节点；仅取 attached 子主题。"""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text)

    def parse_topic(el):
        title = ''
        for t in el.findall('./title'):
            title = (t.text or '').strip()
            break
        pri = None
        for ref in el.findall('./marker-refs/marker-ref'):
            mid = ref.get('marker-id', '')
            if mid in _XMIND_PRI:
                pri = _XMIND_PRI[mid]
                break
        children = []
        for topics in el.findall('./children/topics'):
            if (topics.get('type') or 'attached') == 'detached':
                continue
            for child in topics.findall('./topic'):
                children.append(parse_topic(child))
        return {'title': title, 'priority': pri, 'children': children}

    # 根 topic：content.xml 结构可能带 sheet 包裹，取第一个含 title 的 topic
    first = root.find('.//topic')
    if first is None:
        return {'title': '', 'priority': None, 'children': []}
    return parse_topic(first)


def parse_xmind(path):
    """解析 .xmind（兼容 XMind8 content.xml 与 Zen content.json）→ 用例 dict 列表。

    约定：中心主题=项目/套件名（不计入模块）；中间层级=模块路径；叶子节点=用例标题；
    优先级图标 → P0~P3；XMind 不含执行状态，status_std 统一记「未执行」。
    """
    import zipfile
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if 'content.json' in names:
            data = json.loads(z.read('content.json').decode('utf-8'))
            topic = data[0].get('rootTopic', {}) if isinstance(data, list) \
                else data.get('rootTopic', {})
            tree = _xmind_tree_zen(topic)
        elif 'content.xml' in names:
            tree = _xmind_tree_xml(z.read('content.xml').decode('utf-8'))
        else:
            raise RuntimeError('无法识别的 xmind 结构（缺少 content.xml/content.json）: %s'
                               % path)

    leaves = []

    def walk(node, path):
        np = path + [node['title']] if node['title'] else path
        if not node['children']:
            if node['title']:
                leaves.append({'path': np, 'title': node['title'],
                               'priority': node.get('priority')})
        else:
            for c in node['children']:
                walk(c, np)

    walk(tree, [])
    cases = []
    for i, leaf in enumerate(leaves, start=1):
        # 模块 = 中心主题之后、叶子之前的路径（叶子直挂中心主题时用中心主题名）
        module = '/'.join(leaf['path'][1:-1]) or (leaf['path'][0] or '未分组')
        cases.append({
            'case_id': 'XM-%03d' % i,
            'title': leaf['title'],
            'module': module,
            'priority': leaf['priority'],
            'requirement_id': None,
            'status': None,
            'status_std': '未执行',
            'is_regression': None,
            'duration_min': None,
            'block_reason': None,
            '_from_xmind': True,
            '_source_file': os.path.basename(path),
            '_source_row': i,
        })
    return cases


def parse_testcases(testcase_dir):
    """解析 test_cases/ 全部文件（CSV/Excel/XMind）→ (cases, warnings)。"""
    cases, warnings = [], []
    if not os.path.isdir(testcase_dir):
        return None, ['test_cases/ 目录不存在']
    files = sorted(f for f in os.listdir(testcase_dir)
                   if f.lower().endswith(('.csv', '.xlsx', '.xlsm', '.xmind')))
    if not files:
        return None, ['test_cases/ 目录下无 CSV/Excel/XMind 文件']
    for fn in files:
        path = os.path.join(testcase_dir, fn)
        if fn.lower().endswith('.xmind'):
            try:
                cases.extend(parse_xmind(path))
            except (RuntimeError, ValueError, KeyError) as e:
                warnings.append('文件 %s 解析失败: %s' % (fn, e))
            continue
        try:
            headers, rows = read_table(path)
        except RuntimeError as e:
            warnings.append(str(e))
            continue
        mapping = {}
        for h in headers:
            if not h:
                continue
            nh = norm_header(h)
            for std, candidates in TC_FIELD_MAP.items():
                if std not in mapping.values() and any(nh == norm_header(c) for c in candidates):
                    mapping[nh] = std
                    break
        if 'status' not in mapping.values():
            warnings.append('文件 %s 未识别到「执行状态」列，已跳过' % fn)
            continue
        for idx, row in enumerate(rows, start=2):
            c = {k: None for k in TC_FIELD_MAP}
            for h in headers:
                key = mapping.get(norm_header(h))
                if key:
                    v = row.get(h)
                    if isinstance(v, str):
                        v = v.strip()
                    if v not in (None, '', '无', '-'):
                        c[key] = v
            c['status_std'] = _tc_status_std(c.get('status'))
            c['_source_file'] = fn
            c['_source_row'] = idx
            if c.get('case_id') or c.get('title'):
                cases.append(c)
    return cases, warnings


# ---------------------------------------------------------------------------
# 人员角色名单：{版本目录}/人员角色.csv（姓名,角色；角色 ∈ 前端/后端/产品/测试）
# ---------------------------------------------------------------------------

def load_team_roles(root):
    """读取 {root}/人员角色.csv → {姓名: 角色原文}；文件不存在返回 None。"""
    path = os.path.join(root, '人员角色.csv')
    if not os.path.exists(path):
        return None
    try:
        _, rows = read_table(path)
    except RuntimeError as e:
        raise RuntimeError('人员角色.csv 读取失败: %s' % e)
    roles = {}
    for r in rows:
        name = str(r.get('姓名') or r.get('人员') or r.get('名字') or '').strip()
        role = str(r.get('角色') or r.get('角色/分工') or r.get('分工') or '').strip()
        if name and role:
            roles[name] = role
    return roles or None


# ---------------------------------------------------------------------------
# 指标计算主类
# ---------------------------------------------------------------------------

class Analyzer:
    def __init__(self, dataset, release_time=None, testcase_cases=None,
                 req_change_rows=None, prev_metrics=None, prev_dataset=None,
                 project='', version='', has_req_docs=False, team_roles=None,
                 req_doc_names=None):
        self.dataset = dataset                      # parse 输出的标准中间数据集
        self.bugs = dataset.get('bugs', [])
        self.release_time = release_time            # datetime 或 None
        self.release_time_source = '用户 provided' if release_time else None
        self.cases = testcase_cases                 # list 或 None
        self.req_change_rows = req_change_rows      # 需求变更记录行 或 None
        self.prev_metrics = prev_metrics            # 上一版本指标全量 JSON 或 None
        self.prev_dataset = prev_dataset            # 上一版本标准中间数据集 或 None
        self.project = project
        self.version = version
        self.has_req_docs = has_req_docs            # requirements/ 是否有文件
        self.req_doc_names = req_doc_names or []      # 需求文档名清单（供名称匹配）
        self.team_roles = team_roles                # {姓名: 角色} 或 None（人员角色.csv）
        self.missing = []                           # 缺失项登记（供报告标注）

    # ---- 基础集合 ----------------------------------------------------------

    def _valid_bugs(self):
        return [b for b in self.bugs if not nz.is_invalid_bug(b)]

    def _release_dt(self):
        """发布时间：显式提供 > 缺陷最大创建时间近似（登记口径说明）。"""
        if self.release_time:
            return self.release_time
        dts = [b['created_at_dt'] for b in self.bugs if b.get('created_at_dt')]
        if dts:
            self.release_time_source = '缺陷最大创建时间近似（用户未提供发布时间）'
            return max(dts)
        return None

    # ---- 1. 缺陷大盘 -------------------------------------------------------

    def _find_duplicates(self, valid):
        """重复缺陷：平台标记 ∪ (相似度≥0.8 ∧ 同模块 ∧ 同严重级别)，并聚簇。"""
        n = len(valid)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        flagged_idx = set()
        for i, b in enumerate(valid):
            if b.get('is_duplicate_flag'):
                flagged_idx.add(i)
        if n <= 3000:                               # 相似度两两比对，超大规模仅用平台标记
            for i in range(n):
                for j in range(i + 1, n):
                    a, c = valid[i], valid[j]
                    if (a.get('severity_std') == c.get('severity_std')
                            and (a.get('module') or '') == (c.get('module') or '')
                            and nz.title_similarity(a.get('title'), c.get('title')) >= 0.8):
                        union(i, j)
        else:
            self.missing.append('缺陷数超过3000条，相似度比对降级为仅平台标记识别重复')

        clusters = defaultdict(list)
        for i in range(n):
            clusters[find(i)].append(i)
        dup_groups = [idxs for idxs in clusters.values() if len(idxs) > 1]
        dup_idx = set()
        for idxs in dup_groups:
            dup_idx.update(idxs)
        dup_idx |= flagged_idx
        groups_out = []
        for idxs in dup_groups:
            members = sorted(idxs)
            groups_out.append({
                '代表标题': valid[members[0]].get('title'),
                '数量': len(members),
                '模块': valid[members[0]].get('module') or '未知',
                '严重级别': valid[members[0]].get('severity_std'),
                '成员': [_bug_brief(valid[i])['bug_id'] for i in members],
            })
        return dup_idx, groups_out

    def overview(self):
        valid = self._valid_bugs()
        total = len(self.bugs)
        invalid_total = total - len(valid)
        closed = [b for b in valid if b.get('status_group') == 'closed']
        dup_idx, dup_groups = self._find_duplicates(valid)
        _occ_words = ('偶现', '偶发', '偶尔', '间歇', '不稳定', '无法复现',
                     '不能复现', '复现不了', '概率性', '随机出现')
        occasional = [
            b for b in valid
            if b.get('is_occasional') or any(
                w in (str(b.get('title') or '') + str(b.get('remark') or ''))
                for w in _occ_words)]

        # 存量遗留缺陷
        release_dt = self._release_dt()
        legacy = []
        if release_dt:
            legacy = [b for b in self.bugs
                      if b.get('created_at_dt') and b['created_at_dt'] < release_dt
                      and b.get('status_group') != 'closed']
        else:
            self.missing.append('缺少可用的发布时间与创建时间，存量遗留缺陷无法识别')

        # 规律性反复缺陷：（模块,根因）组合与上一版本交集
        recurring = None
        if self.prev_dataset or (self.prev_metrics or {}).get('module_root_pairs'):
            prev_pairs = set()
            if self.prev_dataset:
                for b in self.prev_dataset.get('bugs', []):
                    if b.get('module') and b.get('root_cause_std'):
                        prev_pairs.add((b['module'], b['root_cause_std']))
            else:
                prev_pairs = {(p[0], p[1]) for p in self.prev_metrics['module_root_pairs']}
            cur_pairs = defaultdict(list)
            for b in valid:
                if b.get('module') and b.get('root_cause_std'):
                    cur_pairs[(b['module'], b['root_cause_std'])].append(b)
            recurring = [{
                '模块': k[0], '根因': k[1],
                '本版数量': len(v),
                '缺陷ID': [_bug_brief(b)['bug_id'] for b in v],
            } for k, v in cur_pairs.items() if k in prev_pairs]
            recurring.sort(key=lambda r: -r['本版数量'])
        else:
            self.missing.append('缺少上一版本缺陷数据，规律性反复缺陷无法识别')

        root_cause_rows = _group_counts(
            [b for b in valid if b.get('root_cause_std')], 'root_cause_std')

        overview = {
            'bug_total': total,
            'invalid_total': invalid_total,
            'valid_total': len(valid),
            'closed_total': len(closed),
            'resolved_rate(%)': _pct(len(closed), len(valid)),
            'by_severity': _group_counts(valid, 'severity_std', SEVERITY_ORDER),
            'by_priority': _group_counts(valid, 'priority_std', ['P0', 'P1', 'P2', 'P3']),
            'by_module': _group_counts(valid, 'module'),
            'duplicates': {
                'count': len(dup_idx),
                'rate(%)': _pct(len(dup_idx), len(valid)),
                'groups': dup_groups,
                'flagged_by_platform': sum(1 for b in valid if b.get('is_duplicate_flag')),
            },
            'recurring': recurring,
            'occasional': {
                'count': len(occasional),
                'rate(%)': _pct(len(occasional), len(valid)),
                'items': [_bug_brief(b) for b in occasional],
            },
            'legacy': {
                'release_time': _dt_iso(release_dt),
                'release_time_source': self.release_time_source,
                'count': len(legacy),
                'items': [_bug_brief(b) for b in legacy],
            },
            'root_cause': root_cause_rows,
            'module_root_pairs': sorted(
                [[b.get('module') or '未知', b.get('root_cause_std')]
                 for b in valid if b.get('root_cause_std')]),
            'dup_idx_ids': {id(b) for b in (valid[i] for i in dup_idx)},
        }
        return overview, valid

    # ---- 2. 人员效能 -------------------------------------------------------

    # 人员角色名单的口径别名（人员角色.csv 的「角色」列取值）
    ROLE_ALIAS = {
        '测试': ['测试', 'qa', 'test', '测试工程师', '测试人员'],
        '前端': ['前端', 'fe', 'frontend', '前端开发', 'web'],
        '后端': ['后端', 'be', 'backend', '后端开发', '服务端', 'java', '服务端开发'],
        '产品': ['产品', 'pm', '产品经理', '需求'],
    }

    def _role(self, name):
        """人员角色（标准化）；未提供名单返回 '__no_list__'，名单未登记返回 None。"""
        if not self.team_roles:
            return '__no_list__'
        raw = self.team_roles.get(name)
        if raw is None:
            return None
        v = re.sub(r'\s+', '', str(raw).lower())
        for std, aliases in self.ROLE_ALIAS.items():
            if v in [str(a).lower() for a in aliases] or v == std.lower():
                return std
        return '其他:' + str(raw).strip()

    def personnel(self, valid, overview):
        dup_ids = overview['dup_idx_ids']
        unregistered = set()                       # 名单未登记人员（提示补填）

        def _role_tag(name):
            r = self._role(name)
            if r == '__no_list__':
                return '按提报近似'
            if r is None:
                unregistered.add(name)
                return '未登记'
            return r

        # 测试人员维度（提报人分组；验证人优先取验证人字段，缺省提报人）
        # 有名单时：仅「测试」角色与「未登记」人员计入；开发/产品自提缺陷不混入
        testers = defaultdict(lambda: {
            'report_count': 0, 'verified_total': 0, 'first_pass': 0,
            'rejected': 0, 'verify_pairs': [], 'dup_count': 0, 'titles': []})
        non_tester_reports = 0
        for b in valid:
            reporter = b.get('reporter') or '未知'
            role = self._role(reporter)
            if role not in ('__no_list__', None, '测试'):
                non_tester_reports += 1             # 开发/产品自提缺陷，不计入测试效能
            else:
                t = testers[reporter]
                t['report_count'] += 1
                t['titles'].append(b.get('title') or '')
                if id(b) in dup_ids:
                    t['dup_count'] += 1
            # 验证记录：缺陷到达过「已解决/已关闭」且验证人=该人（同样按角色过滤）
            verifier = b.get('verifier') or reporter
            v_role = self._role(verifier)
            if v_role in ('__no_list__', None, '测试'):
                if b.get('resolved_at_dt') or b.get('closed_at_dt'):
                    v = testers[verifier]
                    v['verified_total'] += 1
                    if b.get('reopen_count', 0) > 0:
                        v['rejected'] += 1
                    else:
                        v['first_pass'] += 1
                    if b.get('closed_at_dt') and b.get('resolved_at_dt'):
                        v['verify_pairs'].append((b['closed_at_dt'], b['resolved_at_dt']))

        tester_rows = []
        for name in sorted(testers, key=lambda k: -testers[k]['report_count']):
            t = testers[name]
            tester_rows.append({
                '测试人员': name,
                '角色': _role_tag(name) if name != '未知' else '-',
                '提交Bug数': t['report_count'],
                '个人占比(%)': _pct(t['report_count'], len(valid)),
                '验证总数': t['verified_total'],
                '首次验证通过率(%)': _pct(t['first_pass'], t['verified_total']),
                '驳回重修复率(%)': _pct(t['rejected'], t['verified_total']),
                '平均验证时长(小时)': _mean_hours(t['verify_pairs']),
                '重复上报Bug率(%)': _pct(t['dup_count'], t['report_count']),
                'titles_sample': t['titles'][:20],      # 供 AI 做语言风格分析
            })

        # 开发人员维度（解决人优先，缺省经办人）
        # 有名单时：仅「前端/后端」角色与「未登记」人员计入开发效能；
        # 测试/产品人员自解决或代关闭的缺陷（如测试自行处理配置类问题）不混入
        devs = defaultdict(lambda: {
            'fixed_total': 0, 'bounce': 0,
            'fix_pairs_by_sev': defaultdict(list)})
        non_dev_resolved = 0
        for b in valid:
            dev = b.get('resolver') or b.get('assignee') or '未知'
            if not b.get('resolved_at_dt'):
                continue
            role = self._role(dev)
            if role not in ('__no_list__', None, '前端', '后端'):
                non_dev_resolved += 1                 # 测试/产品解决的缺陷，不计入开发效能
                continue
            d = devs[dev]
            d['fixed_total'] += 1
            if b.get('reopen_count', 0) > 0:
                d['bounce'] += 1
            start = self._fix_start(b)
            if start:
                d['fix_pairs_by_sev'][b.get('severity_std') or '未分级'].append(
                    (b['resolved_at_dt'], start))
        dev_rows = []
        for name in sorted(devs, key=lambda k: -devs[k]['fixed_total']):
            d = devs[name]
            row = {
                '开发人员': name,
                '角色': _role_tag(name) if name != '未知' else '-',
                '已修复总数': d['fixed_total'],
                '缺陷回弹率(%)': _pct(d['bounce'], d['fixed_total']),
                '平均修复时长(小时)': _mean_hours(
                    [p for pairs in d['fix_pairs_by_sev'].values() for p in pairs]),
                '分层修复时长': {},
            }
            for sev in SEVERITY_ORDER:
                if d['fix_pairs_by_sev'].get(sev):
                    row['分层修复时长'][sev] = _mean_hours(d['fix_pairs_by_sev'][sev])
            dev_rows.append(row)

        # 角色口径登记（供报告标注与用户核对）
        if self.team_roles:
            if unregistered:
                self.missing.append(
                    '人员角色.csv 未登记人员：%s（相关统计已按「未登记」角色计入，请补填）'
                    % '、'.join(sorted(unregistered)))
            if non_tester_reports:
                self.missing.append(
                    '按角色口径剔除开发/产品自提缺陷 %s 条（不计入测试提报效能）'
                    % non_tester_reports)
            if non_dev_resolved:
                self.missing.append(
                    '按角色口径剔除测试/产品解决缺陷 %s 条（不计入开发修复效能）'
                    % non_dev_resolved)
        else:
            self.missing.append(
                '未提供 人员角色.csv，人员维度按「提报人=测试、解决人=开发」近似，'
                '存在角色混入风险（如测试自解决缺陷计入开发效能），建议填写名单后重跑')

        # 全生命周期耗时分布
        # 响应阶段：分配时间晚于解决时间的样本（禅道「指派日期」为最后一次指派，
        # 通常是解决后指回验证）无法反映首次分配，跳过不计入响应统计
        resp_pairs, fix_pairs = [], []
        for b in valid:
            assigned, created = b.get('assigned_at_dt'), b.get('created_at_dt')
            resolved = b.get('resolved_at_dt')
            assign_usable = assigned and (not resolved or assigned <= resolved)
            if assign_usable and created:
                resp_pairs.append((assigned, created))
            start = self._fix_start(b)
            if resolved and start:
                fix_pairs.append((resolved, start))
        lifecycle = {
            '响应(分配-创建)': self._stage_stats(resp_pairs),
            '修复(解决-分配)': self._stage_stats(fix_pairs),
            '验证(关闭-解决)': self._stage_stats(
                [(b.get('closed_at_dt'), b.get('resolved_at_dt')) for b in valid]),
        }
        return {'testers': tester_rows, 'devs': dev_rows, 'lifecycle': lifecycle}

    def _fix_start(self, bug):
        """修复计时起点：分配时间缺失、或晚于解决时间（如禅道「指派日期」为
        最后一次指派、解决后才指回验证）时，回退创建时间，保证口径确定性。"""
        assigned = bug.get('assigned_at_dt')
        created = bug.get('created_at_dt')
        resolved = bug.get('resolved_at_dt')
        if resolved and assigned and (resolved - assigned).total_seconds() < 0:
            return created
        return assigned or created

    def _stage_stats(self, pairs):
        hours = [(e - s).total_seconds() / 3600
                 for e, s in pairs if e and s and (e - s).total_seconds() >= 0]
        if not hours:
            return {'平均(小时)': None, '样本数': 0, '分布': []}
        dist = defaultdict(int)
        for h in hours:
            dist[_bucket(h)] += 1
        order = [b[0] for b in HOUR_BUCKETS]
        return {
            '平均(小时)': round(sum(hours) / len(hours), 1),
            '样本数': len(hours),
            '分布': [{'区间': k, '数量': dist[k], '占比(%)': _pct(dist[k], len(hours))}
                    for k in order if dist.get(k)],
        }

    # ---- 3. 版本环比 -------------------------------------------------------

    def compare(self, summary_core, overview, personnel):
        if not self.prev_metrics:
            self.missing.append('缺少上一版本复盘指标，版本环比与改进项校验无法分析')
            return None
        prev = self.prev_metrics.get('summary_core') or {}
        cur = summary_core
        keys = ['bug_total', 'valid_total', 'resolved_rate(%)',
                'duplicate_rate(%)', 'occasional_rate(%)',
                'first_pass_rate(%)', 'reject_rate(%)', 'bounce_rate(%)',
                'avg_fix_hours', 'avg_verify_hours']
        labels = {
            'bug_total': 'Bug总数', 'valid_total': '有效缺陷数',
            'resolved_rate(%)': 'Bug解决率(%)', 'duplicate_rate(%)': '重复缺陷率(%)',
            'occasional_rate(%)': '偶现缺陷率(%)', 'first_pass_rate(%)': '整体首过率(%)',
            'reject_rate(%)': '整体驳回率(%)', 'bounce_rate(%)': '整体回弹率(%)',
            'avg_fix_hours': '平均修复时长(小时)', 'avg_verify_hours': '平均验证时长(小时)',
        }
        rows = []
        for k in keys:
            p, c = prev.get(k), cur.get(k)
            delta = round(c - p, 2) if (p is not None and c is not None) else None
            rows.append({'指标': labels[k], '上一版本': p, '本版本': c, '变化': delta})
        return {
            'prev_version': self.prev_metrics.get('meta', {}).get('version'),
            'metrics_delta': rows,
        }

    # ---- 4. 需求侧指标（可确定性计算部分） ----------------------------------

    def requirement_metrics(self, valid):
        urgent, dep_items, req_issue = [], [], []
        for b in valid:
            text = ' '.join(str(x or '') for x in
                            (b.get('title'), b.get('remark'), ' '.join(nz.labels_list(b))))
            if any(k in text for k in URGENT_KEYWORDS):
                urgent.append(b)
            if any(k in text for k in DEPENDENCY_KEYWORDS):
                dep_items.append(b)
            if b.get('root_cause_std') == '需求问题':
                req_issue.append(b)
        # 模块 × 需求根因 关联表
        mod_req = defaultdict(int)
        for b in req_issue:
            mod_req[b.get('module') or '未知'] += 1

        # 需求变更连锁缺陷（若存在变更记录文件）
        change_stats = None
        if self.req_change_rows is not None:
            changed_reqs = defaultdict(int)
            req_titles = {}
            for r in self.req_change_rows:
                rid = str(r.get('需求ID') or r.get('需求编号') or '').strip()
                if rid:
                    changed_reqs[rid] += 1
                    if r.get('需求名称') or r.get('变更内容'):
                        req_titles[rid] = r.get('需求名称') or r.get('变更内容')
            chained = defaultdict(int)
            for b in valid:
                rid = str(b.get('requirement_id') or '').strip()
                if rid and rid in changed_reqs:
                    chained[rid] += 1
            change_stats = {
                '变更需求数': len(changed_reqs),
                '变更总频次': sum(changed_reqs.values()),
                '变更明细': [{'需求ID': rid, '变更次数': n, '关联缺陷数': chained.get(rid, 0),
                              '需求名称': req_titles.get(rid)}
                            for rid, n in sorted(changed_reqs.items())],
                '连锁缺陷总数': sum(chained.values()),
                '连锁缺陷占比(%)': _pct(sum(chained.values()), len(valid)),
            }
        return {
            'urgent_bugs': {
                'count': len(urgent),
                'rate(%)': _pct(len(urgent), len(valid)),
                'items': [_bug_brief(b) for b in urgent],
            },
            'dependency_bugs': {
                'count': len(dep_items),
                'rate(%)': _pct(len(dep_items), len(valid)),
                'items': [_bug_brief(b) for b in dep_items],
            },
            'req_introduced': {
                'count': len(req_issue),
                'rate(%)': _pct(len(req_issue), len(valid)),
                'items': [_bug_brief(b) for b in req_issue],
            },
            'module_req_issues': [{'模块': k, '需求根因缺陷数': v}
                                  for k, v in sorted(mod_req.items(), key=lambda x: -x[1])],
            'change_stats': change_stats,
        }

    # ---- 5. 测试执行指标 ----------------------------------------------------

    def _req_case_match(self):
        """需求-用例关联分析（名称匹配，始终执行）：检查每个需求是否有对应用例，输出漏配清单。
        匹配口径：需求文档名 ↔ 用例模块路径段（归一化后包含或相似度≥0.45）；
        用例数按去重并集统计（一条用例命中即计 1，不因多段命中重复计）。"""
        import difflib
        if not self.req_doc_names or not self.cases:
            return None

        def _norm(s):
            s = re.sub(r'^【[^】]*】', '', str(s or ''))
            return re.sub(r'[\s\-_+（）()【】\[\]、,，.。:：/\\]+', '', s).lower()

        def _hit(nn, key):
            kn = _norm(key)
            if not kn:
                return 0.0
            if nn in kn or kn in nn:
                return 1.0
            r = difflib.SequenceMatcher(None, nn, kn).ratio()
            return r if r >= 0.45 else 0.0

        # 需求清单：按文件逐行列出（不合并同名——【日期】前缀区分延期件与本期件）
        order = []
        for fn in self.req_doc_names:
            name = os.path.splitext(str(fn))[0].strip()
            if name and name not in order:
                order.append(name)
        if not order:
            return None

        rows, misses = [], []
        for name in order:
            nn = _norm(name)
            matched_ids, seg_scores = set(), defaultdict(float)
            for idx, c in enumerate(self.cases):
                segs = set(str(c.get('module') or '').split('/'))
                for s in segs:
                    r = _hit(nn, s)
                    if r > 0:
                        matched_ids.add(idx)
                        seg_scores[s.strip()] = max(seg_scores.get(s.strip(), 0), r)
            label = name
            if matched_ids:
                tops = sorted(seg_scores, key=lambda s: -seg_scores[s])[:3]
                rows.append({
                    '需求': label,
                    '命中用例组': '、'.join(
                        (s[:18] + '…') if len(s) > 18 else s for s in tops),
                    '用例数': len(matched_ids), '判定': '已覆盖'})
            else:
                rows.append({'需求': label, '命中用例组': '（无）', '用例数': 0,
                             '判定': '疑似漏配'})
                misses.append(label)
        return {'需求总数': len(order),
                '已覆盖': len(order) - len(misses),
                '疑似漏配': len(misses),
                '漏配清单': misses, '明细': rows}

    def testcase_metrics(self, valid):
        if not self.cases:
            self.missing.append('缺少 test_cases/ 测试用例文件，用例执行与覆盖率指标无法分析')
            return None
        cases = self.cases
        xmind_n = sum(1 for c in cases if c.get('_from_xmind'))
        if xmind_n:
            self.missing.append(
                'test_cases 含 %d 条 XMind 用例（无执行状态字段），执行类指标'
                '（执行覆盖率/阻塞/回归）不分析、不出现在报告中' % xmind_n)
        total = len(cases)
        counter = defaultdict(int)
        for c in cases:
            counter[c['status_std']] += 1
        executed = counter['通过'] + counter['失败']

        # 需求-用例双向覆盖
        reqs_in_cases = {str(c.get('requirement_id')).strip()
                         for c in cases if c.get('requirement_id')}
        reqs_in_bugs = {str(b.get('requirement_id')).strip()
                        for b in valid if b.get('requirement_id')}
        covered = reqs_in_bugs & reqs_in_cases
        cases_with_req = [c for c in cases if c.get('requirement_id')]
        # 关联能力探测：①缺陷↔用例编号 join 是否可行（需求编号双向存在）②用例是否带执行状态字段
        status_field_present = any(c.get('status') for c in cases)
        defect_case_linkable = bool(reqs_in_cases and reqs_in_bugs)

        # 阻塞事件分类
        blocked = [c for c in cases if c['status_std'] == '阻塞']
        block_counter = defaultdict(list)
        for c in blocked:
            reason = str(c.get('block_reason') or '')
            cat = '其他'
            for std, kws in BLOCK_REASON_RULES:
                if any(k in reason for k in kws):
                    cat = std
                    break
            block_counter[cat].append(c)

        # 回归工作量
        def _is_reg(c):
            raw = str(c.get('is_regression') or '')
            return raw in ('是', 'Y', 'y', 'yes', 'True', 'true', '回归')
        reg_cases = [c for c in cases if _is_reg(c)]
        reg_minutes = 0.0
        for c in reg_cases:
            try:
                reg_minutes += float(str(c.get('duration_min') or 0).replace('分钟', '') or 0)
            except ValueError:
                pass

        return {
            'case_total': total,
            'exec_trackable': status_field_present,
            'defect_case_linkable': defect_case_linkable,
            'req_case_match': self._req_case_match(),
            'status_dist': [{'状态': s, '数量': counter[s], '占比(%)': _pct(counter[s], total)}
                            for s in ('通过', '失败', '阻塞', '跳过', '未执行') if counter[s]],
            'executed': executed,
            'exec_coverage(%)': _pct(executed, total),
            'req_coverage': {
                '缺陷关联需求数': len(reqs_in_bugs),
                '被用例覆盖数': len(covered),
                '需求被用例覆盖比例(%)': _pct(len(covered), len(reqs_in_bugs)) if reqs_in_bugs else None,
                '用例关联需求完整率(%)': _pct(len(cases_with_req), total),
                '未覆盖需求清单': sorted(reqs_in_bugs - reqs_in_cases),
            },
            'blocked_events': {
                'total': len(blocked),
                'by_category': [{'分类': k, '数量': len(v),
                                 '用例': [c.get('case_id') or c.get('title') for c in v]}
                                for k, v in sorted(block_counter.items(), key=lambda x: -len(x[1]))],
            },
            'regression': {
                'regression_case_count': len(reg_cases),
                'regression_duration_min': round(reg_minutes, 1) if reg_minutes else None,
            },
            'per_module': self._module_case_stats(cases, valid),
        }

    def _module_case_stats(self, cases, valid):
        stats = defaultdict(lambda: {'case_total': 0, '通过': 0, '失败': 0,
                                     '回归用例': 0})
        for c in cases:
            m = c.get('module') or '未知'
            stats[m]['case_total'] += 1
            if c['status_std'] in ('通过', '失败'):
                stats[m][c['status_std']] += 1
            if str(c.get('is_regression') or '') in ('是', 'Y', 'y', 'yes', 'True', 'true'):
                stats[m]['回归用例'] += 1
        bug_by_mod = defaultdict(int)
        for b in valid:
            bug_by_mod[b.get('module') or '未知'] += 1
        modules = set(stats) | set(bug_by_mod)
        rows = []
        for m in modules:
            s = stats.get(m, {'case_total': 0, '通过': 0, '失败': 0, '回归用例': 0})
            executed = s['通过'] + s['失败']
            rows.append({
                '模块': m, 'Bug数': bug_by_mod.get(m, 0),
                '用例数': s['case_total'], '已执行': executed, '失败': s['失败'],
                '回归用例': s['回归用例'],
                '失败率(%)': _pct(s['失败'], executed) if executed else None,
            })
        rows.sort(key=lambda r: -r['Bug数'])
        return rows

    # ---- 6. 自动化优先级 + 漏测风险扫描 --------------------------------------

    def automation_priority(self, valid):
        """评分 = 0.3核心 + 0.2回归频率 + 0.2手工成本 + 0.2缺陷密度 + 0.1稳定性
        （各维按模块归一化 0~1；缺用例数据时仅缺陷维并降权归一）。P0前20% / P1次30% / P2其余。"""
        bug_by_mod = defaultdict(int)
        for b in valid:
            bug_by_mod[b.get('module') or '未知'] += 1
        case_stats = {}
        if self.cases:
            case_stats = {r['模块']: r for r in self._module_case_stats(self.cases, valid)}
        modules = sorted(set(bug_by_mod) | set(case_stats),
                         key=lambda m: -bug_by_mod.get(m, 0))
        if not modules:
            return None
        has_case = bool(case_stats)
        rows = []
        for m in modules:
            bugs = bug_by_mod.get(m, 0)
            cs = case_stats.get(m)
            reg = cs['回归用例'] if cs else 0
            executed = cs['已执行'] if cs else 0
            cases_n = cs['用例数'] if cs else 0
            failrate = (cs['失败率(%)'] if cs and cs['失败率(%)'] is not None else None)
            rows.append({
                '模块': m, 'Bug数': bugs, '用例数': cases_n,
                '回归用例数': reg, '已执行用例数': executed, '失败率(%)': failrate,
                '_density': (bugs / cases_n) if cases_n else (1.0 if bugs else 0.0),
            })
        max_bug = max((r['Bug数'] for r in rows), default=0) or 1
        max_reg = max((r['回归用例数'] for r in rows), default=0) or 1
        max_exe = max((r['已执行用例数'] for r in rows), default=0) or 1
        max_den = max((r['_density'] for r in rows), default=0) or 1

        for r in rows:
            core = r['Bug数'] / max_bug
            if has_case:
                regress = r['回归用例数'] / max_reg
                cost = r['已执行用例数'] / max_exe
                density = r['_density'] / max_den
                stability = 1 - (r['失败率(%)'] or 0) / 100.0
                score = 0.3 * core + 0.2 * regress + 0.2 * cost + \
                    0.2 * density + 0.1 * stability
                dims = '全维度(缺陷+用例)'
            else:
                score = core                              # 缺用例时降级：仅缺陷维度
                dims = '降级：仅缺陷维度（无用例数据）'
            r['评分'] = round(score, 3)
            r['_dims'] = dims

        rows.sort(key=lambda r: -r['评分'])
        n = len(rows)
        p0 = math.ceil(n * 0.2)
        p1 = math.ceil(n * 0.3)
        for i, r in enumerate(rows):
            r['优先级'] = 'P0' if i < p0 else ('P1' if i < p0 + p1 else 'P2')
            r['投入产出评级'] = '高' if r['评分'] >= 0.6 else ('中' if r['评分'] >= 0.35 else '低')
        for r in rows:
            r['评分维度'] = r.pop('_dims')
            r.pop('_density')
        if not has_case:
            self.missing.append('缺少测试用例数据，自动化评分降级为仅缺陷维度')
        return {'modules': rows,
                'formula': '总分=0.3×业务核心度+0.2×回归执行频率+0.2×手工测试成本'
                           '+0.2×历史缺陷密度+0.1×场景稳定性（按模块归一化）',
                'priority_rule': '排序后 P0=前20%、P1=次30%、P2=其余；'
                                 '投入产出评级：≥0.6高 / ≥0.35中 / 其余低'}

    def risk_scan(self, valid):
        """高风险场景关键词扫描 + 模块缺陷-用例 gap 清单（供 AI 补充漏测分析）。"""
        hits = defaultdict(list)
        for b in valid:
            text = str(b.get('title') or '') + ' ' + str(b.get('remark') or '')
            for cat, kws in RISK_KEYWORDS.items():
                if any(k in text for k in kws):
                    hits[cat].append(_bug_brief(b)['bug_id'])
        gaps = []
        if self.cases:
            stats = {r['模块']: r for r in self._module_case_stats(self.cases, valid)}
            for m, r in stats.items():
                if r['Bug数'] > 0 and r['用例数'] == 0:
                    gaps.append({'模块': m, 'Bug数': r['Bug数'], '用例数': 0,
                                 '信号': '有缺陷无用例，疑似漏测高风险'})
                elif r['Bug数'] > 0 and r['失败'] == 0 and r['用例数'] > 0:
                    gaps.append({'模块': m, 'Bug数': r['Bug数'], '用例数': r['用例数'],
                                 '失败用例': 0, '信号': '有缺陷但无用例失败，覆盖深度存疑'})
        return {'keyword_hits': {k: v for k, v in hits.items() if v},
                'module_gaps': gaps}

    # ---- 汇总 ---------------------------------------------------------------

    def build(self):
        if not self.has_req_docs:
            self.missing.append('缺少 requirements/ 需求文档，需求评审类定性分析无法执行')
        overview, valid = self.overview()
        personnel = self.personnel(valid, overview)
        if self.team_roles:
            _known = set(self.team_roles)
            _seen = set()
            for b in self.bugs:
                for f in ('报告人', '经办人', '解决人', '验证人'):
                    n = str(b.get(f) or '').strip()
                    if n and n not in _known:
                        _seen.add(n)
            if _seen:
                self.missing.append(
                    '人员角色.csv 未登记人员：%s（已按「未登记」口径计入对应统计，'
                    '建议补全名单）' % '、'.join(sorted(_seen)))
        req = self.requirement_metrics(valid)
        tc = self.testcase_metrics(valid)
        auto = self.automation_priority(valid)
        risk = self.risk_scan(valid)

        # 整体核心指标（供版本环比，跨版本口径稳定）
        all_verify = [b for b in valid if b.get('resolved_at_dt') or b.get('closed_at_dt')]
        first_pass = sum(1 for b in all_verify if b.get('reopen_count', 0) == 0)
        fixed = [b for b in valid if b.get('resolved_at_dt')]
        bounced = sum(1 for b in fixed if b.get('reopen_count', 0) > 0)
        summary_core = {
            'bug_total': overview['bug_total'],
            'valid_total': overview['valid_total'],
            'resolved_rate(%)': overview['resolved_rate(%)'],
            'duplicate_rate(%)': overview['duplicates']['rate(%)'],
            'occasional_rate(%)': overview['occasional']['rate(%)'],
            'first_pass_rate(%)': _pct(first_pass, len(all_verify)),
            'reject_rate(%)': _pct(len(all_verify) - first_pass, len(all_verify)),
            'bounce_rate(%)': _pct(bounced, len(fixed)),
            'avg_fix_hours': _mean_hours([(b['resolved_at_dt'], self._fix_start(b))
                                          for b in fixed]),
            'avg_verify_hours': _mean_hours([(b['closed_at_dt'], b['resolved_at_dt'])
                                             for b in valid if b.get('closed_at_dt')
                                             and b.get('resolved_at_dt')]),
        }
        compare = self.compare(summary_core, overview, personnel)

        return {
            'meta': {
                'project': self.project,
                'version': self.version,
                'platform': self.dataset.get('meta', {}).get('platform'),
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'input_files': self.dataset.get('meta', {}).get('input_files', []),
                'release_time': overview['legacy']['release_time'],
                'release_time_source': overview['legacy']['release_time_source'],
            },
            'summary_core': summary_core,
            'overview': {k: v for k, v in overview.items() if k != 'dup_idx_ids'},
            'personnel': personnel,
            'requirement': req,
            'testcases': tc,
            'automation': auto,
            'risk_scan': risk,
            'compare': compare,
            'missing': sorted(set(self.missing)),
        }
