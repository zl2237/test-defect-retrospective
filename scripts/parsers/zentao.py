# -*- coding: utf-8 -*-
"""禅道（ZenTao）Bug 导出文件解析插件（CSV / Excel）。

覆盖禅道 Bug 列表标准导出字段：
Bug编号 / Bug标题 / 所属模块 / 严重程度(1-4) / 优先级(1-4) / Bug状态(激活/已解决/已关闭)
由谁创建 / 指派给 / 解决者 / 由谁关闭 / 创建日期 / 指派日期 / 解决日期 / 关闭日期
解决方案 / 激活次数 / 关键词 / 相关需求 / 重现步骤 / 重复Bug / 影响版本 等。
数字型严重程度与优先级由 normalize.py 统一映射（1→致命/P0 … 4→轻微/P3）。

禅道导出值多带「(#id)/(#code)」后缀（如「已关闭(#closed)」「/订单管理(#102)」），
纯引用「(#0)」表示空——由 to_standard 钩子统一清洗后再做值级标准化。
"""
import re

import normalize as nz
from .base import BaseParser


def _clean_zentao(value):
    """禅道导出值清洗：纯引用「(#0)」置空；去尾部「(#xxx)」后缀。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r'\(#[^)]*\)', s):        # 纯引用值，如 "(#0)" → 空
        return None
    s = re.sub(r'\s*\(#?[^)]*\)\s*$', '', s).strip()   # 去尾部 "(#xxx)" 后缀
    return s or None


# 需要 (#id) 后缀清洗的文本字段
_CLEAN_KEYS = ('bug_id', 'title', 'status', 'severity', 'priority', 'module',
               'reporter', 'assignee', 'resolver', 'verifier', 'resolution',
               'root_cause', 'labels', 'requirement_id', 'repro', 'remark',
               'duplicate_of', 'found_version')


class ZentaoParser(BaseParser):
    name = 'zentao'
    label = '禅道'

    field_map = {
        'bug_id': ['ID', 'Bug编号', '编号', 'Bug ID'],
        'title': ['Bug标题', 'bug标题', '标题', 'Bug名称'],
        'status': ['状态', '当前状态', 'Bug状态', 'bug状态'],
        'severity': ['严重程度', '严重级别', '级别'],
        'priority': ['优先级'],
        'module': ['模块', '所属模块', '模块名称', '一级模块', '产品'],
        'reporter': ['创建者', '由谁创建', '创建人', '提出人'],
        'assignee': ['指派给', '当前指派', '指派人', '处理人', '由谁指派'],
        'resolver': ['由谁解决', '解决者', '解决人'],
        'verifier': ['关闭者', '由谁关闭', '验证人'],
        'created_at': ['创建日期', '创建时间'],
        'assigned_at': ['指派日期', '指派时间'],
        'resolved_at': ['解决日期', '解决时间'],
        'closed_at': ['关闭日期', '关闭时间'],
        'resolution': ['解决方案', '解决结果'],
        'root_cause': ['根因', '原因', '根本原因'],
        'reopen_count': ['激活次数', '重开次数'],
        'labels': ['关键词', '标签'],
        'requirement_id': ['关联需求', '需求', '需求ID', '相关需求'],
        'repro': ['复现概率', '重现概率', '复现率'],
        'remark': ['复现步骤', '步骤', '重现步骤', '备注'],
        'duplicate_of': ['重复关联', '重复Bug', '重复bug'],
        'found_version': ['影响版本', '影响版本(当前触发)', '所属版本'],
    }

    # 表头特征：用于 auto 探测
    signature_headers = ['bug标题', '严重程度', '解决方案', '激活次数', '由谁创建', '指派给']

    def to_standard(self, std):
        """禅道值清洗：去 (#id) 后缀、模块路径去前导斜杠，再走通用标准化。"""
        for k in _CLEAN_KEYS:
            std[k] = _clean_zentao(std.get(k))
        if std.get('module'):
            std['module'] = std['module'].lstrip('/')
        return nz.normalize_bug(std)
