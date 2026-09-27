# -*- coding: utf-8 -*-
"""普惠AI · Phase3 候选模板人工审核入口（对应《完整落地思路.docx》49/68 行）

用法（宿主/老板都能跑）：
    python -m fanrenge.review --pending              # 列出待审候选（含来源、hits、质检结果）
    python -m fanrenge.review --approve <id>         # 审核通过 → 并入模板库
    python -m fanrenge.review --reject  <id> [理由]  # 驳回（进 rejected，可追溯）
    python -m fanrenge.review --check   <id>         # 只跑质量闸门，不入库

设计原则：**引擎只提炼、不自动入库**；入库必须走这里（人工审核）——防止字典被垃圾模板污染。
"""
import io
import os
import sys

if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fanrenge import engine as E
else:
    from . import engine as E


def _show(d, idx=None):
    q = d.get('来源') or {}
    ok, why = E.quality_check(d)
    print('%s id=%s ｜ %s/%s/%s' % (('%2d.' % idx) if idx else '   ', d.get('id'),
                                    d.get('industry'), d.get('scene'), d.get('task')))
    print('      目标: %s' % d.get('goal'))
    print('      必填: %s ｜ 关键词: %s' % ('、'.join(d.get('required') or []),
                                          '、'.join((d.get('match') or [])[:6])))
    print('      步骤: %d 条 ｜ 来源: %s ｜ 出现次数: %s ｜ 质检: %s' % (
        len(d.get('steps') or []), q.get('type', '?'), q.get('hits', 1),
        ('通过' if ok else '不通过（%s）' % why)))
    if q.get('from_text'):
        print('      原始需求: %s' % q['from_text'])


def cmd_pending():
    data = E.list_pending()
    ps = data.get('pending') or []
    print('=== 待审候选模板：%d 条（模板库现有 %d 个）===' % (len(ps), len(E.load_templates()['templates'])))
    for i, d in enumerate(ps, 1):
        _show(d, i)
    if not ps:
        print('   （空 —— 说明还没有"没匹配到模板"的自由模式任务产生候选）')
    rj = data.get('rejected') or []
    if rj:
        print('已驳回 %d 条（保留可追溯）' % len(rj))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 0
    a = argv[0]
    if a == '--pending':
        return cmd_pending()
    if a == '--check' and len(argv) > 1:
        d = next((x for x in E.list_pending()['pending'] if x.get('id') == argv[1]), None)
        if not d:
            print('没找到候选 %s' % argv[1])
            return 1
        _show(d)
        ok, why = E.quality_check(d)
        print('质检结论: %s' % ('通过 ✅' if ok else '不通过 ❌ %s' % why))
        return 0 if ok else 1
    if a == '--approve' and len(argv) > 1:
        ok, msg = E.approve_draft(argv[1])
        print(('✅ ' if ok else '❌ ') + msg)
        return 0 if ok else 1
    if a == '--reject' and len(argv) > 1:
        ok, msg = E.reject_draft(argv[1], ' '.join(argv[2:]) or '人工驳回')
        print(('✅ ' if ok else '❌ ') + msg)
        return 0 if ok else 1
    print(__doc__)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
