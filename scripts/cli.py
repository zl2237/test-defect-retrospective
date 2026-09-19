# -*- coding: utf-8 -*-
"""测试缺陷复盘 Skill —— CLI 入口。

子命令：
  session  问卷会话管理（断点续跑：show / set / reset）
  init     初始化 {项目名}/{版本号}/ 标准输入目录
  scan     素材校验，输出缺失素材清单（前置校验）
  parse    解析 defects/ 导出文件 → 统一标准中间数据集
  analyze  计算全量指标 → 生成产品/开发/测试三类产物（MD+JSON）
  all      scan + parse + analyze 串联

用法示例（在 Skill 目录下执行）：
  python scripts/cli.py session show
  python scripts/cli.py init --root "项目A/v2.4.0"
  python scripts/cli.py scan --root "项目A/v2.4.0"
  python scripts/cli.py parse --root "项目A/v2.4.0"
  python scripts/cli.py analyze --root "项目A/v2.4.0" --release-time "2026-09-01 10:00"
"""
import argparse
import glob
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

# 问卷题目顺序（断点续跑依据）
SESSION_QUESTIONS = ['defect_platform', 'req_platform', 'req_format',
                     'testcase_source', 'has_prev_report']
DEFECT_DIRS = ('defects', 'requirements', 'test_cases', 'reports')


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
# scan：素材校验（前置校验，输出缺失素材清单）
# ---------------------------------------------------------------------------

def _list_input_files(path):
    if not os.path.isdir(path):
        return []
    out = []
    for f in sorted(os.listdir(path)):
        if f.lower().endswith(('.csv', '.xlsx', '.xlsm', '.xls')):
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
    reqs = _list_input_files(os.path.join(root, 'requirements'))
    reqs_all = ([f for f in sorted(os.listdir(os.path.join(root, 'requirements')))]
                if os.path.isdir(os.path.join(root, 'requirements')) else [])
    tcs = _list_input_files(os.path.join(root, 'test_cases'))
    team_role_file = os.path.join(root, '人员角色.csv')

    result['defects_files'] = defects
    result['requirements_files'] = reqs_all
    result['testcase_files'] = tcs
    result['team_role_file'] = os.path.basename(team_role_file) \
        if os.path.exists(team_role_file) else None
    if not os.path.exists(team_role_file):
        result['warnings'].append(
            '未找到 人员角色.csv（姓名,角色；角色：前端/后端/产品/测试），'
            '人员效能将按「提报人=测试、解决人=开发」近似，存在角色混入风险')
    if not defects:
        result['missing'].append('defects/ 目录缺少缺陷导出文件（CSV/Excel），核心分析无法执行')
    if not reqs_all:
        result['missing'].append('requirements/ 目录为空，需求评审类章节将标注数据缺失')
    if not tcs:
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
# parse：解析缺陷导出 → 统一标准中间数据集
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
# analyze：全量指标 + 三类产物
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
    if not scan.get('defects_files'):
        raise SystemExit('缺失素材：defects/ 无缺陷导出文件，分析终止（详见上方缺失清单）')
    cmd_parse(args)
    return cmd_analyze(args)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description='测试缺陷复盘 Skill CLI')
    sub = ap.add_subparsers(dest='cmd', required=True)

    sp = sub.add_parser('session', help='问卷会话（断点续跑）')
    sp.add_argument('action', choices=['show', 'set', 'reset'])
    sp.add_argument('--project')
    sp.add_argument('--version')
    sp.add_argument('--answer', action='append',
                    help='key=value，可重复，如 --answer defect_platform=jira')
    sp.set_defaults(func=cmd_session)

    sp = sub.add_parser('init', help='初始化 {项目名}/{版本号} 目录')
    sp.add_argument('--root', required=True)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser('scan', help='素材校验，输出缺失素材清单')
    sp.add_argument('--root', required=True)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser('parse', help='解析缺陷导出 → 标准中间数据集')
    sp.add_argument('--root', required=True)
    sp.add_argument('--platform', default='auto',
                    choices=['auto', 'jira', 'zentao', 'custom'])
    sp.set_defaults(func=cmd_parse)

    sp = sub.add_parser('analyze', help='全量指标计算 + 三类产物生成')
    sp.add_argument('--root', required=True)
    sp.add_argument('--release-time', help='当前版本发布时间 YYYY-MM-DD HH:MM')
    sp.add_argument('--prev-root', help='上一版本目录（默认语义排序自动探测）')
    sp.add_argument('--defects-file', help='指定标准中间数据集 JSON（默认取最新）')
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser('all', help='scan + parse + analyze 串联')
    sp.add_argument('--root', required=True)
    sp.add_argument('--release-time')
    sp.add_argument('--prev-root')
    sp.add_argument('--platform', default='auto',
                    choices=['auto', 'jira', 'zentao', 'custom'])
    sp.set_defaults(func=cmd_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
