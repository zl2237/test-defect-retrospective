# -*- coding: utf-8 -*-
"""缺陷平台解析器注册表（插件化架构入口）。

新增平台支持 = 新增模块文件 + 在 PARSER_REGISTRY 注册一项；
主分析逻辑（analyzer / reporter / cli）不做任何修改。
"""
from .base import BaseParser, norm_header, read_table  # noqa: F401
from .jira import JiraParser
from .zentao import ZentaoParser
from .custom import CustomParser

PARSER_REGISTRY = {
    JiraParser.name: JiraParser,
    ZentaoParser.name: ZentaoParser,
    CustomParser.name: CustomParser,
}


def get_parser(name):
    """按平台名取解析器实例；custom 需要映射文件存在。"""
    cls = PARSER_REGISTRY.get(name)
    if cls is None:
        raise RuntimeError('未知解析平台: %s（可选: %s）' % (name, '/'.join(PARSER_REGISTRY)))
    return cls()


def detect_platform(headers):
    """按表头特征自动探测平台，返回 jira / zentao / None。"""
    normed = {norm_header(h) for h in headers if h}
    for parser_cls in (JiraParser, ZentaoParser):
        hits = sum(1 for s in parser_cls.signature_headers if s in normed)
        # Jira 特征表头命中 1 个即可判定；禅道特征需命中 2 个（字段名较通用）
        need = 1 if parser_cls is JiraParser else 2
        if hits >= need:
            return parser_cls.name
    return None
