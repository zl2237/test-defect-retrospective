# -*- coding: utf-8 -*-
"""docx 需求文档文本提取工具（标准库实现，无需 python-docx）。

用途：requirements/ 目录下的 Word 需求文档（.docx）在纯需求定性评审前，
先用本工具提取纯文本；被删除线标记的段落（废弃需求范围）会加
「[删除线] 」前缀输出，供 AI 识别需求版本演进与范围矛盾。

用法（在 Skill 目录下执行）：
  python scripts/docx_extract.py "<docx 路径>"            # 提取到标准输出
  python scripts/docx_extract.py "<docx 路径>" -o out.txt  # 提取到文件

说明：.docx 本质为 zip 包，正文位于 word/document.xml；
本工具不解析图片（图片内容按缺失规则标注）与页眉页脚。
"""
import argparse
import re
import sys
import zipfile


def extract_docx_text(path):
    """提取 docx 正文纯文本；返回带「[删除线] 」前缀标记的文本。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if 'word/document.xml' not in names:
            raise RuntimeError('不是有效的 .docx 文件（缺少 word/document.xml）: %s' % path)
        xml = z.read('word/document.xml').decode('utf-8')

    xml = xml.replace('</w:p>', '\n')                 # 段落 → 换行
    lines, struck = [], set()
    for idx, ln in enumerate(xml.split('\n')):
        # 删除线检测：显式 true 或无取值属性视为启用；显式 false/0 视为关闭
        if '<w:strike/>' in ln or '<w:strike w:val="true"/>' in ln or (
                '<w:strike' in ln and 'w:val="false"' not in ln
                and 'w:val="0"' not in ln):
            struck.add(idx)
        text = re.sub(r'<[^>]+>', '', ln)              # 去掉所有 XML 标签
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            lines.append(('[删除线] ' if idx in struck else '') + text)

    out = '\n'.join(lines)
    for k, v in (('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                 ('&quot;', '"'), ('&apos;', "'")):
        out = out.replace(k, v)
    return out


def main():
    ap = argparse.ArgumentParser(description='docx 需求文档文本提取（含删除线检测）')
    ap.add_argument('docx', help='.docx 文件路径')
    ap.add_argument('-o', '--output', help='输出到文件（默认打印到标准输出）')
    args = ap.parse_args()
    text = extract_docx_text(args.docx)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print('written: %s (%d chars)' % (args.output, len(text)))
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(text)


if __name__ == '__main__':
    main()
