# -*- coding: utf-8 -*-
"""Jira 导出文件解析插件（CSV / Excel）。

覆盖 Jira 中文与英文标准导出表头，以及常见自定义字段（根因、验证人、关联需求等）。
"""
from .base import BaseParser, norm_header


class JiraParser(BaseParser):
    name = 'jira'
    label = 'Jira'

    # 标准字段 → Jira 原始表头候选
    field_map = {
        'bug_id': ['Issue key', '问题键', 'Key', '编号', '问题编号'],
        'title': ['Summary', '摘要', '标题', '主题'],
        'status': ['Status', '状态'],
        'severity': ['Severity', '严重级别', '严重程度'],
        'priority': ['Priority', '优先级'],
        'module': ['Components', '组件', '模块', '所属模块', 'Epic Link', 'Epic链接', 'Epic名称'],
        'reporter': ['Reporter', '报告人', '创建人', '提出人'],
        'assignee': ['Assignee', '经办人', '负责人', '指派给', '处理人', '分配给'],
        'resolver': ['Resolver', '解决人'],
        'verifier': ['Verifier', '验证人', '验收人'],
        'created_at': ['Created', '创建', '创建时间', '创建日期'],
        'assigned_at': ['Assigned', '指派时间', '分配时间', '指派日期'],
        'resolved_at': ['Resolved', '已解决', '解决时间', '解决日期'],
        'closed_at': ['Closed', '关闭', '关闭时间', '关闭日期', '结案时间'],
        'resolution': ['Resolution', '解决结果', '解决方案'],
        'root_cause': ['Root Cause', '根因', '缺陷根因', '根本原因', '引入原因', '问题原因'],
        'reopen_count': ['Reopen', '重开次数', 'Reopen Count', '重新打开次数'],
        'labels': ['Labels', '标签'],
        'requirement_id': ['需求ID', '关联需求', 'Requirement', '需求编号', 'Story'],
        'repro': ['复现概率', 'Reproducibility', '复现率', '重现概率'],
        'remark': ['Description', '描述', '复现步骤', '备注', 'Comment', '重现步骤'],
        'duplicate_of': ['Duplicate of', '重复关联', '关联重复'],
        'found_version': ['Affects Version/s', '影响版本', '发现版本'],
    }

    # 表头特征：用于 auto 探测
    signature_headers = ['issuekey', '问题键', 'summary', '摘要']
