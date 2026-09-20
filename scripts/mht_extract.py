#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MHTML 文本提取器：将「.doc/.mht/.mhtml 后缀但实为 MHTML 网页存档」的文档提取为纯文本。

背景：飞书/腾讯文档等「另存为 Word」常产出 MHTML 格式但扩展名为 .doc，
docx_extract.py（面向 OOXML docx）无法读取。本工具用标准库 email 模块解析 MIME，
抽取 text/html（去标签）或 text/plain 部分。

用法：
  python scripts/mht_extract.py <输入文件或目录> [-o 输出目录]
  # 目录输入时递归处理 *.doc/*.mht/*.mhtml；输出目录缺省为输入旁的 extracted_txt/
"""
import argparse
import email
import email.policy
import glob
import html
import os
import re
import sys


def html_to_text(h):
    h = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', h, flags=re.S | re.I)
    h = re.sub(r'<br\s*/?>', '\n', h, flags=re.I)
    h = re.sub(r'</(p|div|tr|li|h[1-6]|table)>', '\n', h, flags=re.I)
    h = re.sub(r'</(td|th)>', '\t', h, flags=re.I)
    h = re.sub(r'<[^>]+>', '', h)
    h = html.unescape(h)
    h = re.sub(r'\n\s*\n+', '\n', h)
    return h.strip()


def extract(path):
    with open(path, 'rb') as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)
    texts = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct == 'text/html':
            texts.append(html_to_text(part.get_content()))
        elif ct == 'text/plain' and not texts:
            texts.append(part.get_content())
    return '\n'.join(t for t in texts if t)


def main():
    ap = argparse.ArgumentParser(description='MHTML(伪装 .doc) → 纯文本提取')
    ap.add_argument('input', help='输入 .doc/.mht/.mhtml 文件或所在目录')
    ap.add_argument('-o', '--out', help='输出目录（缺省：输入旁 extracted_txt/）')
    args = ap.parse_args()

    src = args.input
    if os.path.isdir(src):
        files = []
        for ext in ('*.doc', '*.mht', '*.mhtml'):
            files += glob.glob(os.path.join(src, '**', ext), recursive=True)
        out_dir = args.out or os.path.join(src, 'extracted_txt')
    else:
        files = [src]
        out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(src)), 'extracted_txt')
    os.makedirs(out_dir, exist_ok=True)

    ok = skip = 0
    for path in files:
        try:
            text = extract(path)
        except Exception as e:
            print('[跳过] %s：%s' % (path, e))
            skip += 1
            continue
        name = os.path.splitext(os.path.basename(path))[0] + '.txt'
        with open(os.path.join(out_dir, name), 'w', encoding='utf-8') as f:
            f.write(text)
        print('[OK] %s => %s（%d 字符）' % (os.path.basename(path), name, len(text)))
        ok += 1
    print('完成：%d 提取 / %d 跳过 → %s' % (ok, skip, out_dir))


if __name__ == '__main__':
    main()
