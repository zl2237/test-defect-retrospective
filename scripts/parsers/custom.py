# -*- coding: utf-8 -*-
"""自定义平台解析插件：读取 scripts/custom_field_map.json 的「原始表头→标准字段」映射。

用于问卷 Q1 选择「其他」缺陷平台的场景。AI 在问卷阶段根据用户描述的字段说明
生成该映射文件后，本插件即可将任意平台导出解析为统一标准中间数据集。
"""
import json
import os

from .base import BaseParser, STANDARD_FIELDS

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'custom_field_map.json')


class CustomParser(BaseParser):
    name = 'custom'
    label = '自定义平台'

    def __init__(self, config_file=None):
        self.field_map = {k: [] for k in STANDARD_FIELDS}
        path = config_file or CONFIG_FILE
        if not os.path.exists(path):
            raise RuntimeError(
                '未找到自定义字段映射文件 %s。'
                '请先根据用户提供的字段说明生成该文件（格式见 SKILL.md 附录C）。' % path)
        with open(path, 'r', encoding='utf-8') as f:
            raw_to_std = json.load(f)          # {原始表头: 标准字段}
        for raw, std in raw_to_std.items():
            if std in self.field_map:
                self.field_map[std].append(raw)

    signature_headers = []                     # 自定义平台不做自动探测
