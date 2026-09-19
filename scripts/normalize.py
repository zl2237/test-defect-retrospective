# -*- coding: utf-8 -*-
"""值级标准化模块：状态 / 严重程度 / 优先级 / 解决结果 / 根因等字段归一化。

所有平台解析器（Jira / 禅道 / 自定义）输出的原始值统一经过本模块转换，
形成与源平台完全解耦的标准中间数据集。修改口径需同步更新 SKILL.md 第三节。
"""
import re
from datetime import datetime
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# 状态分组：open(打开) / in_progress(处理中) / resolved(已解决) / closed(已关闭)
# 注意：「已解决」不计入解决率分子，仅「已关闭/已验证通过」计入。
# ---------------------------------------------------------------------------
_STATUS_GROUPS = [
    ('closed', ['closed', 'close', 'done', '已关闭', '关闭', '已完成', '已完结',
                '已验证', '已验证通过', 'verified', '已验收']),
    ('resolved', ['resolved', 'resolve', 'fixed', '已解决', '解决', '已修复',
                  '修复完成', '待验证', '待测试验证', 'ready for qa', 'in qa']),
    ('in_progress', ['in progress', 'processing', '处理中', '进行中', '开发中',
                     '修复中', 'investigating', 'reopened', '重新打开', '重开']),
    ('open', ['open', 'to do', 'todo', 'backlog', 'new', 'created', '待办',
              '新建', '打开', '激活', 'active', '待处理', '未处理', '待指派']),
]

# 严重程度：致命/严重/一般/轻微/建议（禅道数字 1-4 → 致命/严重/一般/轻微）
_SEVERITY_GROUPS = [
    ('致命', ['致命', 'fatal', 'blocker', 'highest', 's1', '1']),
    ('严重', ['严重', 'critical', 'high', 's2', '2']),
    ('一般', ['一般', '中等', '主要', 'major', 'medium', 's3', '3']),
    ('轻微', ['轻微', '次要', 'minor', 'low', 's4', '4']),
    ('建议', ['建议', '提示', 'trivial', 'lowest', 's5', '5']),
]

# 优先级：P0/P1/P2/P3
_PRIORITY_GROUPS = [
    ('P0', ['p0', 'highest', '紧急', 'urgent', '1', '立即处理']),
    ('P1', ['p1', 'high', '高', '重要', '2']),
    ('P2', ['p2', 'medium', '中', '一般', 'normal', '3']),
    ('P3', ['p3', 'low', '低', 'lowest', 'trivial', '4']),
]

# 解决结果标准值。INVALID_RESOLUTIONS 中的值判定为无效缺陷（不计入有效总数）
INVALID_RESOLUTION_STD = ['重复', '设计如此', '无法重现', '无效', '转需求']
_RESOLUTION_STD = {
    '已修复': ['fixed', '已修复', '修复', '解决', 'done', '已解决', 'complete'],
    '重复': ['duplicate', '重复', '重复缺陷', '重复提交', 'dup'],
    '设计如此': ['by design', "won't fix", 'wont fix', 'wontfix', '设计如此', '不予解决', '不需要修复'],
    '无法重现': ['cannot reproduce', 'can not reproduce', '无法重现', '无法复现', '不能重现'],
    '无效': ['invalid', '无效', 'not a bug', '误报'],
    '转需求': ['转需求', 'requirement', '转为需求'],
    '延期处理': ['延期', '延期处理', 'deferred', '挂起'],
}

# 根因预置7类（关键词包含匹配，中英文）+ 未分类
_ROOT_CAUSE_RULES = [
    ('需求问题', ['需求', 'prd', '需求不清', '需求变更', '需求遗漏', 'requirement']),
    ('代码逻辑', ['代码', '逻辑', '编码', '实现', '空指针', '异常', '报错',
                  'code', 'logic', 'null pointer']),
    ('环境配置', ['环境', '配置', '部署', '服务器', '参数', '发布', '端口',
                  'environment', 'config', 'deploy', 'server', 'infrastructure']),
    ('数据问题', ['数据', '脏数据', '脚本数据', '初始化', '缓存数据', 'dirty data']),
    ('设计缺陷', ['设计', '方案', '架构', '交互设计', '概要设计',
                  'design', 'architecture', 'schema']),
    ('兼容性问题', ['兼容', '适配', '浏览器', '分辨率', '机型', '版本兼容', '系统版本',
                    'compatib', 'browser', 'device']),
    ('操作失误', ['操作', '使用不当', '误操作', '手动改动', '人为',
                  'operation', 'misuse', 'manual change']),
]
ROOT_CAUSE_DEFAULT = '未分类'

# 偶现缺陷关键词（备注/复现概率字段）
_OCCASIONAL_KEYWORDS = ['难以复现', '难以重现', '偶现', '偶发', '复现率低', '低概率复现', '小概率']
_PROB_RE = re.compile(r'(\d{1,3})\s*%')
_LOW_PROB_RE = re.compile(r'[<＜]\s*30\s*%|小于\s*30\s*%|低于\s*30\s*%')

# 日期时间解析格式（按顺序尝试）
_DATETIME_FORMATS = [
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d',
    '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M', '%Y/%m/%d',
    '%Y年%m月%d日 %H:%M:%S', '%Y年%m月%d日 %H:%M', '%Y年%m月%d日',
    '%d/%m/%Y %H:%M', '%m/%d/%Y %H:%M',
    '%d/%b/%y %I:%M %p', '%d/%b/%y %H:%M', '%d/%b/%Y %H:%M',
    '%Y.%m.%d %H:%M:%S', '%Y.%m.%d',
]


def _norm(value):
    """字符串归一化：去空白、转小写（用于别名精确比较）。"""
    return re.sub(r'\s+', '', str(value or '').strip().lower())


def _match_group(value, groups, default=None):
    """先精确匹配，再包含匹配，返回标准值；无法匹配返回 default。"""
    if value is None:
        return default
    v = _norm(value)
    if not v:
        return default
    for std, aliases in groups:                      # 第一轮：精确匹配
        if v == _norm(std) or v in [_norm(a) for a in aliases]:
            return std
    for std, aliases in groups:                      # 第二轮：包含匹配（如「已关闭(Closed)」）
        for a in aliases:
            if _norm(a) and _norm(a) in v:
                return std
    return default


def status_group(raw):
    """原始状态 → open/in_progress/resolved/closed/unknown。"""
    return _match_group(raw, _STATUS_GROUPS, 'unknown')


def severity_std(raw):
    return _match_group(raw, _SEVERITY_GROUPS, '未分级')


def priority_std(raw):
    return _match_group(raw, _PRIORITY_GROUPS, '未分级')


def resolution_std(raw):
    """原始解决结果 → 标准值（已修复/重复/设计如此/无法重现/无效/转需求/延期处理/其他/None）。"""
    if raw is None:
        return None
    v = _norm(raw)
    if not v:
        return None
    for std, aliases in _RESOLUTION_STD.items():
        if v in [_norm(a) for a in aliases]:
            return std
    for std, aliases in _RESOLUTION_STD.items():
        for a in aliases:
            if _norm(a) and _norm(a) in v:
                return std
    return '其他'


def is_invalid_bug(bug):
    """无效缺陷：解决结果判定为 重复/设计如此/无法重现/无效/转需求。"""
    return bug.get('resolution_std') in INVALID_RESOLUTION_STD


def root_cause_std(raw):
    """根因关键词归类到预置7类；有值但不命中任何关键词 → 未分类；无值 → None。"""
    if raw is None or not str(raw).strip():
        return None
    v = str(raw).lower()
    for std, keywords in _ROOT_CAUSE_RULES:
        for k in keywords:
            if k in v or k in str(raw):
                return std
    return ROOT_CAUSE_DEFAULT


def is_occasional(repro, *texts):
    """偶现缺陷：复现概率<30% 或 文本含偶现关键词。"""
    for t in (repro,) + texts:
        if t is None:
            continue
        s = str(t)
        for kw in _OCCASIONAL_KEYWORDS:
            if kw in s:
                return True
        if _LOW_PROB_RE.search(s):
            return True
        m = _PROB_RE.search(s)
        if m and int(m.group(1)) < 30:
            return True
    return False


def parse_datetime(raw):
    """多格式日期时间解析，失败返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    # Jira ISO 格式（2026-08-30T11:00:00.000+0800）→ 截取前 19 位规范格式
    m = re.match(r'^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})', s)
    if m:
        s = m.group(1) + ' ' + m.group(2)
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def title_fingerprint(title):
    """标题指纹：去空白与标点、转小写，用于相似度比对。"""
    return re.sub(r'[^\w]+', '', str(title or '').lower())


def title_similarity(a, b):
    """标题相似度（0~1），difflib 确定性计算。"""
    fa, fb = title_fingerprint(a), title_fingerprint(b)
    if not fa or not fb:
        return 0.0
    return SequenceMatcher(None, fa, fb).ratio()


def version_key(version):
    """版本号语义排序键：v2.10.0 > v2.9.0（按数字段比较）。"""
    parts = re.split(r'[^\w]+', str(version or '').lower())
    key = []
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            key.append((1, int(p), ''))
        else:
            key.append((0, 0, p))
    return key


def labels_list(bug):
    """标签字段（字符串或列表）→ 列表。"""
    raw = bug.get('labels')
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in re.split(r'[,;，；\s]+', str(raw)) if x.strip()]


def normalize_bug(bug):
    """对单条缺陷完成值级标准化（原地补充派生字段）。"""
    bug['status_group'] = status_group(bug.get('status'))
    bug['severity_std'] = severity_std(bug.get('severity'))
    bug['priority_std'] = priority_std(bug.get('priority'))
    bug['resolution_std'] = resolution_std(bug.get('resolution'))
    bug['root_cause_std'] = root_cause_std(bug.get('root_cause'))
    bug['is_occasional'] = is_occasional(bug.get('repro'), bug.get('remark'), bug.get('title'))
    bug['is_duplicate_flag'] = (bug.get('resolution_std') == '重复') or bool(str(bug.get('duplicate_of') or '').strip())
    for k in ('created_at', 'assigned_at', 'resolved_at', 'closed_at'):
        bug[k + '_dt'] = parse_datetime(bug.get(k))
    try:
        bug['reopen_count'] = int(str(bug.get('reopen_count') or '0').strip() or 0)
    except (TypeError, ValueError):
        bug['reopen_count'] = 0
    return bug
