# -*- coding: utf-8 -*-
"""CLI 入口：session / init / scan / parse / analyze / html / all。

模式路由：defects 有文件 → 复盘模式（parse→analyze）；无 defects 时
requirements/test_cases/tech_designs 有文件 → 定性评审模式（AI 评审 + html 文档模式）。
test_cases 支持 CSV/Excel/XMind。

问卷（4 题，每题均影响分析执行）：缺陷平台→解析插件；发布时间→遗留缺陷基准；
上版数据→环比；角色名单→人员效能口径。

用法示例（在 Skill 目录下执行）：
  python scripts/cli.py session show
  python scripts/cli.py init --root "项目A/v2.4.0"
  python scripts/cli.py scan   --root "项目A/v2.4.0"   # 素材校验 + 模式路由判定
  python scripts/cli.py parse  --root "项目A/v2.4.0"   # 复盘模式
  python scripts/cli.py analyze --root "项目A/v2.4.0" --release-time "2026-09-01 10:00"
  python scripts/cli.py html   --root "项目A/v2.4.0"   # 仪表板/文档模式自动识别
"""
import argparse
import glob
import io
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import normalize as nz                              # noqa: E402
from parsers import get_parser, detect_platform     # noqa: E402
from parsers.base import read_table                 # noqa: E402
import analyzer as az                               # noqa: E402
import reporter                                     # noqa: E402

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSION_FILE = os.path.join(SKILL_DIR, '.session.json')

# 问卷题目顺序（断点续跑依据）——每题均直接影响分析执行：
# 平台→解析插件；发布时间→存量遗留判定；上版→环比；角色名单→人员效能口径
SESSION_QUESTIONS = ['defect_platform', 'release_time', 'has_prev_report',
                     'team_roles']
# 输入目录（全部可选，按存在文件路由评审模式）
# defects → 复盘模式；requirements/test_cases/tech_designs → 定性评审模式
DEFECT_DIRS = ('defects', 'requirements', 'test_cases', 'tech_designs', 'reports')


def _ts():
    return time.strftime('%Y%m%d_%H%M%S')


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# session：问卷状态（断点续跑）
# ---------------------------------------------------------------------------

def _load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'project': None, 'version': None, 'answers': {}, 'updated_at': None}


def _save_session(sess):
    sess['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(SESSION_FILE, 'w', encoding='utf-8') as f:
        json.dump(sess, f, ensure_ascii=False, indent=2)


def cmd_session(args):
    sess = _load_session()
    if args.action == 'reset':
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
        print(json.dumps({'reset': True}, ensure_ascii=False))
        return
    if args.action == 'set':
        if args.project:
            sess['project'] = args.project
        if args.version:
            sess['version'] = args.version
        for kv in args.answer or []:
            if '=' not in kv:
                raise SystemExit('参数格式错误，应为 --answer key=value，收到: %s' % kv)
            k, v = kv.split('=', 1)
            # 布尔值规范化
            if v.lower() in ('true', '是'):
                v = True
            elif v.lower() in ('false', '否'):
                v = False
            sess['answers'][k] = v
        _save_session(sess)
    # show / set 均输出当前状态
    answered = [q for q in SESSION_QUESTIONS if sess['answers'].get(q) is not None]
    _print_json({
        'project': sess.get('project'),
        'version': sess.get('version'),
        'answers': sess['answers'],
        'answered_questions': answered,
        'answers_complete': len(answered) == len(SESSION_QUESTIONS),
        'next_question': next((q for q in SESSION_QUESTIONS
                               if sess['answers'].get(q) is None), None),
        'updated_at': sess.get('updated_at'),
    })


# ---------------------------------------------------------------------------
# init：初始化输入目录
# ---------------------------------------------------------------------------

def cmd_init(args):
    root = args.root.rstrip('/\\')
    project, version = _split_root(root)
    for d in DEFECT_DIRS:
        os.makedirs(os.path.join(root, d), exist_ok=True)
    _print_json({'root': root, 'project': project, 'version': version,
                 'created_dirs': list(DEFECT_DIRS)})


def _split_root(root):
    parts = [p for p in root.replace('\\', '/').split('/') if p]
    if len(parts) < 2:
        raise SystemExit('路径必须符合 {项目名}/{版本号}/ 规范，收到: %s' % root)
    return parts[-2], parts[-1]


# ---------------------------------------------------------------------------
# scan：素材校验 + 模式路由判定（前置校验，输出缺失素材清单）
# ---------------------------------------------------------------------------

def _list_input_files(path, exts=('.csv', '.xlsx', '.xlsm', '.xls')):
    if not os.path.isdir(path):
        return []
    out = []
    for f in sorted(os.listdir(path)):
        if f.lower().endswith(exts):
            out.append(f)
    return out


def _latest(reports_dir, prefix):
    if not os.path.isdir(reports_dir):
        return None
    files = sorted(glob.glob(os.path.join(reports_dir, prefix + '*.json')))
    return files[-1] if files else None


def detect_prev_version(root):
    """同项目下按版本号语义排序取上一版本目录。"""
    root = root.rstrip('/\\')
    project_dir = os.path.dirname(root)
    current = os.path.basename(root)
    if not os.path.isdir(project_dir):
        return None
    siblings = [d for d in os.listdir(project_dir)
                if d != current
                and os.path.isdir(os.path.join(project_dir, d))]
    cur_key = nz.version_key(current)
    older = [(nz.version_key(d), d) for d in siblings if nz.version_key(d) < cur_key]
    if not older:
        return None
    older.sort()
    return os.path.join(project_dir, older[-1][1])


def cmd_scan(args):
    root = args.root.rstrip('/\\')
    result = {'root': root, 'root_exists': os.path.isdir(root), 'missing': [],
              'warnings': []}
    if not result['root_exists']:
        result['missing'].append('目录 %s 不存在，请先执行 init' % root)
        _print_json(result)
        return result

    defects = _list_input_files(os.path.join(root, 'defects'))
    reqs_all = ([f for f in sorted(os.listdir(os.path.join(root, 'requirements')))]
                if os.path.isdir(os.path.join(root, 'requirements')) else [])
    tcs = _list_input_files(os.path.join(root, 'test_cases'),
                            exts=('.csv', '.xlsx', '.xlsm', '.xls', '.xmind'))
    team_role_file = os.path.join(root, '人员角色.csv')
    # 技术方案文档（docx/md/txt 等全量文件均计入，不做扩展名过滤）
    techs_all = ([f for f in sorted(os.listdir(os.path.join(root, 'tech_designs')))]
                 if os.path.isdir(os.path.join(root, 'tech_designs')) else [])

    result['defects_files'] = defects
    result['requirements_files'] = reqs_all
    result['testcase_files'] = tcs
    result['tech_design_files'] = techs_all
    result['team_role_file'] = os.path.basename(team_role_file) \
        if os.path.exists(team_role_file) else None
    if not os.path.exists(team_role_file):
        result['warnings'].append(
            '未找到 人员角色.csv（姓名,角色；角色：前端/后端/产品/测试），'
            '人员效能将按「提报人=测试、解决人=开发」近似，存在角色混入风险')

    # 模式路由：defects 有文件 → 复盘模式；否则按各目录内容做定性评审
    if defects:
        result['mode'] = 'retrospective'
        if techs_all:
            result['warnings'].append(
                '检测到 tech_designs/ 文件，复盘完成后应追加技术方案评审报告')
    else:
        result['mode'] = 'review'
        reviewable = []
        if reqs_all:
            reviewable.append('需求评审(requirements)')
        if tcs:
            reviewable.append('测试用例评审(test_cases)')
        if techs_all:
            reviewable.append('技术方案评审(tech_designs)')
        if reviewable:
            result['missing'].append(
                '未检测到缺陷导出 → 进入定性评审模式：%s' % '、'.join(reviewable))
        else:
            result['missing'].append('所有输入目录均为空，无可分析素材')
    if not reqs_all and defects:
        result['missing'].append('requirements/ 目录为空，需求评审类章节将标注数据缺失')
    if not tcs and defects:
        result['missing'].append('test_cases/ 目录为空，用例执行/覆盖率类章节将标注数据缺失')

    prev_root = detect_prev_version(root)
    result['prev_version'] = None
    if prev_root:
        prev_json = _latest(os.path.join(prev_root, 'reports'), '复盘数据_指标全量_')
        result['prev_version'] = {
            'path': prev_root, 'version': os.path.basename(prev_root),
            'has_metrics': bool(prev_json)}
        if not prev_json:
            result['warnings'].append(
                '检测到上一版本目录 %s 但无指标JSON，环比将标注缺失' % prev_root)
    else:
        result['missing'].append('未找到上一版本目录或其报告，版本环比将标注数据缺失')

    reports_dir = os.path.join(root, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    scan_file = os.path.join(reports_dir, '素材校验_%s.json' % _ts())
    with open(scan_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    result['scan_report'] = scan_file
    _print_json(result)
    return result


# ---------------------------------------------------------------------------
# parse：解析缺陷导出 → 统一标准中间数据集（复盘模式）
# ---------------------------------------------------------------------------

def _parse_defects(root, platform):
    defects_dir = os.path.join(root, 'defects')
    files = _list_input_files(defects_dir)
    if not files:
        raise SystemExit('defects/ 目录无 CSV/Excel 文件，请先补充缺陷导出文件')
    dataset = {'meta': {'platform': None, 'input_files': [],
                        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')},
               'bugs': [], 'unmapped_columns': [], 'warnings': []}
    for fn in files:
        path = os.path.join(defects_dir, fn)
        use_platform = platform
        if platform in (None, 'auto'):
            headers, _ = read_table(path)
            use_platform = detect_platform(headers) or 'custom'
        parser = get_parser(use_platform)
        part = parser.parse_file(path)
        if not part.get('required_ok', True):
            # 明细表（改动记录/评论等：仅 key/标题可映射、无状态列）不并入缺陷集，
            # 避免其按文件名排序在前时抢占 bug_id|标题 去重、污染主表字段
            dataset['meta']['input_files'].append('%s（跳过：非缺陷主表）' % fn)
            dataset['unmapped_columns'] += ['%s: %s' % (fn, c) for c in part['unmapped_columns']]
            dataset['warnings'] += part['warnings']
            continue
        dataset['meta']['input_files'].append(fn)
        dataset['meta']['platform'] = dataset['meta']['platform'] or parser.label
        dataset['bugs'].extend(part['bugs'])
        dataset['unmapped_columns'] += ['%s: %s' % (fn, c) for c in part['unmapped_columns']]
        dataset['warnings'] += part['warnings']
    # 按 bug_id 去重（多文件重复导出场景）
    seen, deduped = set(), []
    for b in dataset['bugs']:
        key = str(b.get('bug_id') or '') + '|' + str(b.get('title') or '')
        if key in seen:
            continue
        seen.add(key)
        deduped.append(b)
    dataset['bugs'] = deduped
    # datetime 对象 → ISO 字符串（JSON 可序列化；analyze 侧会重新解析）
    for b in dataset['bugs']:
        for k in ('created_at_dt', 'assigned_at_dt', 'resolved_at_dt', 'closed_at_dt'):
            dt = b.get(k)
            b[k] = dt.strftime('%Y-%m-%d %H:%M:%S') if hasattr(dt, 'strftime') else dt
    return dataset


def cmd_parse(args):
    root = args.root.rstrip('/\\')
    project, version = _split_root(root)
    dataset = _parse_defects(root, args.platform)
    reports_dir = os.path.join(root, 'reports')
    os.makedirs(reports_dir, exist_ok=True)
    out = os.path.join(reports_dir, '中间数据_缺陷标准集_%s.json' % _ts())
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)
    _print_json({
        'output': out,
        'platform': dataset['meta']['platform'],
        'input_files': dataset['meta']['input_files'],
        'bug_count': len(dataset['bugs']),
        'unmapped_columns': dataset['unmapped_columns'][:50],
        'warnings': dataset['warnings'],
    })
    return out


# ---------------------------------------------------------------------------
# analyze：全量指标 + 三类产物（复盘模式）
# ---------------------------------------------------------------------------

def _load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _parse_req_changes(root):
    """可选的需求变更记录文件：requirements/需求变更记录.csv（列含需求ID/变更内容）。"""
    path = os.path.join(root, 'requirements', '需求变更记录.csv')
    if not os.path.exists(path):
        return None
    _, rows = read_table(path)
    return rows


def cmd_analyze(args):
    root = args.root.rstrip('/\\')
    project, version = _split_root(root)
    reports_dir = os.path.join(root, 'reports')
    defects_file = getattr(args, 'defects_file', None) or _latest(
        reports_dir, '中间数据_缺陷标准集_')
    if not defects_file or not os.path.exists(defects_file):
        raise SystemExit('未找到标准中间数据集，请先执行 parse')
    dataset = _load_json(defects_file)

    # 时间字段反序列化（JSON 中为字符串）
    for b in dataset.get('bugs', []):
        for k in ('created_at_dt', 'assigned_at_dt', 'resolved_at_dt', 'closed_at_dt'):
            b[k] = nz.parse_datetime(b.get(k))

    release_time = nz.parse_datetime(args.release_time) if args.release_time else None
    cases, tc_warnings = az.parse_testcases(os.path.join(root, 'test_cases'))
    req_changes = _parse_req_changes(root)

    # 上一版本：--prev-root 优先，否则语义排序自动探测
    prev_root = args.prev_root or detect_prev_version(root)
    prev_metrics, prev_dataset = None, None
    if prev_root:
        pm = _latest(os.path.join(prev_root, 'reports'), '复盘数据_指标全量_')
        if pm:
            prev_metrics = _load_json(pm)
        pd_ = _latest(os.path.join(prev_root, 'reports'), '中间数据_缺陷标准集_')
        if pd_:
            prev_dataset = _load_json(pd_)

    req_dir = os.path.join(root, 'requirements')
    has_req_docs = os.path.isdir(req_dir) and bool(os.listdir(req_dir))
    team_roles = az.load_team_roles(root)

    ana = az.Analyzer(
        dataset, release_time=release_time, testcase_cases=cases,
        req_change_rows=req_changes, prev_metrics=prev_metrics,
        prev_dataset=prev_dataset, project=project, version=version,
        has_req_docs=has_req_docs, team_roles=team_roles)
    ana.missing.extend(tc_warnings)
    metrics = ana.build()
    files = reporter.write_reports(metrics, reports_dir)
    _print_json({
        'project': project, 'version': version,
        'bug_total': metrics['overview']['bug_total'],
        'resolved_rate(%)': metrics['overview']['resolved_rate(%)'],
        'missing': metrics['missing'],
        'outputs': files,
    })
    return files


def cmd_all(args):
    scan = cmd_scan(args)
    if scan.get('mode') != 'retrospective':
        raise SystemExit('scan 判定非复盘模式（无缺陷导出），请走定性评审流程；'
                         '详见上方缺失清单')
    cmd_parse(args)
    return cmd_analyze(args)


# ---------------------------------------------------------------------------
# html：汇总 HTML（复盘=仪表板模式 / 评审=文档模式，自动识别）
# ---------------------------------------------------------------------------

def _md_sections(md_text):
    """从 Markdown 报告提取 {章节标题: 正文md}；剔除头部「缺失素材清单」（总览页已有档案框展示）。"""
    sections = {}
    parts = md_text.split('\n## ')
    for p in parts[1:]:
        lines = p.split('\n', 1)
        if len(lines) == 2 and lines[0].strip() != '缺失素材清单':
            sections[lines[0].strip()] = lines[1].strip()
    return sections


def cmd_html(args):
    import io
    root = args.root.rstrip('/\\')
    reports_dir = os.path.join(root, 'reports')
    metrics_file = getattr(args, 'metrics_file', None) or _latest(
        reports_dir, '复盘数据_指标全量_')
    # 文档模式：--doc 指定 md；或无指标 JSON 时自动渲染各类型评审报告（每类取最新一份）
    doc_file = getattr(args, 'doc', None)
    if doc_file is None and not (metrics_file and os.path.exists(metrics_file)):
        doc_files = []
        for prefix in ('需求评审报告_', '用例评审报告_', '技术评审报告_'):
            docs = sorted(glob.glob(os.path.join(reports_dir, prefix + '*.md')))
            if docs:
                doc_files.append((prefix, docs[-1]))
        if doc_files:
            outs = []
            stamp_map = {'需求评审报告_': '需求评审', '用例评审报告_': '用例评审',
                         '技术评审报告_': '技术评审'}
            for prefix, df in doc_files:
                outs.append(reporter.write_doc_html(
                    df, reports_dir, stamp=stamp_map.get(prefix, '评审')))
            _print_json({'outputs': outs, 'mode': 'doc',
                         'source_docs': [os.path.basename(d) for _, d in doc_files]})
            return outs
    if doc_file:
        if not os.path.exists(doc_file):
            raise SystemExit('未找到文档: %s' % doc_file)
        out = reporter.write_doc_html(doc_file, reports_dir)
        _print_json({'output': out, 'mode': 'doc',
                     'source_doc': os.path.basename(doc_file)})
        return out
    if not metrics_file or not os.path.exists(metrics_file):
        raise SystemExit('未找到指标全量 JSON（请先执行 analyze）或任一评审报告 md')
    metrics = _load_json(metrics_file)

    sections_by_cat = {}
    for cat in ('产品', '开发', '测试'):
        mds = sorted(glob.glob(os.path.join(reports_dir, '复盘报告_%s_*.md' % cat)))
        if mds:
            with io.open(mds[-1], 'r', encoding='utf-8') as f:
                sections_by_cat[cat] = {t: reporter.md_block_to_html(b)
                                        for t, b in _md_sections(f.read()).items()}
        else:
            sections_by_cat[cat] = {}
    out = reporter.write_html(metrics, sections_by_cat, reports_dir)
    _print_json({'output': out, 'mode': 'dashboard',
                 'source_metrics': os.path.basename(metrics_file)})
    return out


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='测试缺陷复盘与文档评审 Skill CLI')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('session', help='问卷会话（断点续跑）')
    sp.add_argument('action', choices=['show', 'set', 'reset'])
    sp.add_argument('--project')
    sp.add_argument('--version')
    sp.add_argument('--answer', action='append',
                    help='key=value，可重复，如 --answer defect_platform=jira')
    sp.set_defaults(func=cmd_session)

    sp = sub.add_parser('init', help='初始化 {项目名}/{版本号} 目录（含 tech_designs）')
    sp.add_argument('--root', required=True)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser('scan', help='素材校验 + 模式路由判定（复盘/定性评审）')
    sp.add_argument('--root', required=True)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser('parse', help='[复盘模式] 解析缺陷导出 → 标准中间数据集')
    sp.add_argument('--root', required=True)
    sp.add_argument('--platform', default='auto',
                    choices=['auto', 'jira', 'zentao', 'custom'])
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser('analyze', help='[复盘模式] 全量指标计算 + 三类产物生成')
    sp.add_argument('--root', required=True)
    sp.add_argument('--release-time', help='当前版本发布时间 YYYY-MM-DD HH:MM')
    sp.add_argument('--prev-root', help='上一版本目录（默认语义排序自动探测）')
    sp.add_argument('--defects-file', help='指定标准中间数据集 JSON（默认取最新）')
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser('all', help='[复盘模式] scan + parse + analyze 串联')
    sp.add_argument('--root', required=True)
    sp.add_argument('--release-time')
    sp.add_argument('--prev-root')
    sp.add_argument('--platform', default='auto',
                    choices=['auto', 'jira', 'zentao', 'custom'])
    sp.set_defaults(func=cmd_all)

    sp = sub.add_parser('html', help='生成汇总 HTML（复盘=仪表板模式 / 评审=文档模式，自动识别）')
    sp.add_argument('--root', required=True)
    sp.add_argument('--metrics-file', help='指定指标全量 JSON（默认取最新）')
    sp.add_argument('--doc', help='指定 Markdown 报告渲染为档案风 HTML（文档模式）')
    sp.set_defaults(func=cmd_html)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
