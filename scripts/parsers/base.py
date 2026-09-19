# -*- coding: utf-8 -*-
"""解析器基类：统一表格读取（CSV/Excel、多编码）、字段映射、平台插件基类。

插件化架构说明：
- 新增缺陷平台支持时，只需新增一个 BaseParser 子类并在 parsers/__init__.py 的
  PARSER_REGISTRY 注册一项，主分析逻辑（analyzer / reporter / cli）无需任何修改。
- 所有解析器输出统一标准中间数据集（字段清单见 STANDARD_FIELDS），
  与源平台完全解耦。
"""
import csv
import io
import os

import normalize as nz

# 标准中间数据集字段清单（与 SKILL.md 附录A 一致）
STANDARD_FIELDS = [
    'bug_id', 'title', 'status', 'severity', 'priority', 'module',
    'reporter', 'assignee', 'resolver', 'verifier',
    'created_at', 'assigned_at', 'resolved_at', 'closed_at',
    'resolution', 'root_cause', 'reopen_count', 'labels',
    'requirement_id', 'repro', 'remark', 'duplicate_of', 'found_version',
]

# 表头归一化：去空白/下划线/连字符，转小写，用于匹配
def norm_header(h):
    return nz._norm(h).replace('_', '').replace('-', '').replace('/', '')


# ---------------------------------------------------------------------------
# 表格读取：CSV（自动探测编码与分隔符）/ Excel（openpyxl，可选依赖）
# ---------------------------------------------------------------------------

def _read_text(path):
    """按候选编码依次尝试读取文本（禅道导出常为 GBK 系）。"""
    for enc in ('utf-8-sig', 'gb18030', 'utf-8', 'utf-16'):
        try:
            with open(path, 'r', encoding=enc, newline='') as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise RuntimeError('无法识别文件编码: %s' % path)


def read_csv(path):
    """读取 CSV → (headers, rows[dict])，自动探测分隔符（, ; 制表符）。"""
    text = _read_text(path)
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=',;\t')
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    rows = [dict(r) for r in reader]
    headers = list(reader.fieldnames or [])
    return headers, rows


def read_excel(path):
    """读取 xlsx/xlsm → (headers, rows[dict])。需 openpyxl（可选依赖）。"""
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError('读取 Excel 需要安装 openpyxl（pip install openpyxl），'
                           '或改用 CSV 格式导出后重试: %s' % path)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        return [], []
    headers = [str(h).strip() if h is not None else '' for h in rows[0]]
    data = []
    for r in rows[1:]:
        row = {}
        for i, h in enumerate(headers):
            if h:
                row[h] = r[i] if i < len(r) else None
        if any(v not in (None, '') for v in row.values()):
            data.append(row)
    return headers, data


def read_table(path):
    """按扩展名分派读取，返回 (headers, rows[dict])。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm'):
        return read_excel(path)
    return read_csv(path)


# ---------------------------------------------------------------------------
# 解析器基类
# ---------------------------------------------------------------------------

class BaseParser:
    """平台解析器基类：子类只需定义 name / label / field_map / signature_headers。"""

    name = 'base'
    label = '通用'
    # 标准字段 → 原始表头候选列表（匹配时对表头做归一化比较）
    field_map = {k: [] for k in STANDARD_FIELDS}
    # 平台表头特征（用于 auto 探测），元素为归一化表头
    signature_headers = []

    def match_fields(self, headers):
        """原始表头 → 标准字段 映射（一对一，后匹配不覆盖）。"""
        mapping = {}
        used = set()
        for h in headers:
            if not h:
                continue
            nh = norm_header(h)
            if nh in used:
                continue
            for std, candidates in self.field_map.items():
                if std in mapping:
                    continue
                if any(nh == norm_header(c) for c in candidates):
                    mapping[nh] = std
                    used.add(nh)
                    break
        return mapping

    def to_standard(self, std):
        """值级标准化钩子，默认调用通用标准化。"""
        return nz.normalize_bug(std)

    def parse_file(self, path):
        """解析单个导出文件 → 统一标准数据集分片。"""
        headers, rows = read_table(path)
        mapping = self.match_fields(headers)
        bugs, warnings = [], []
        unmapped = [h for h in headers
                    if h and norm_header(h) not in mapping]
        required_missing = [f for f in ('bug_id', 'title', 'status')
                            if f not in mapping.values()]
        if required_missing:
            warnings.append('文件 %s 缺少关键列映射: %s（请检查导出字段或 custom_field_map.json）'
                            % (os.path.basename(path), '、'.join(required_missing)))
        for idx, row in enumerate(rows, start=2):
            std = {k: None for k in STANDARD_FIELDS}
            for h in headers:
                key = mapping.get(norm_header(h))
                if not key:
                    continue
                v = row.get(h)
                if isinstance(v, str):
                    v = v.strip()
                if v not in (None, '', '无', '-'):
                    std[key] = v
            std['_source_file'] = os.path.basename(path)
            std['_source_row'] = idx
            bug = self.to_standard(std)
            if bug.get('bug_id') or bug.get('title'):
                bugs.append(bug)
        if not bugs:
            warnings.append('文件 %s 未解析出任何缺陷记录' % os.path.basename(path))
        return {
            'source_file': os.path.basename(path),
            'platform': self.name,
            'bugs': bugs,
            'unmapped_columns': unmapped,
            'warnings': warnings,
        }
