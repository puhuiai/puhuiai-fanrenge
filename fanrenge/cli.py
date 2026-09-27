# -*- coding: utf-8 -*-
"""普惠AI 引擎B · 命令行演示/自测入口（零算力，不联网）

用法：
  python -m fanrenge.cli --demo                   # 跑 3 个行业的完整闭环演示（有据可查）
  python -m fanrenge.cli "帮我做一条90秒的房产短视频，突出南北通透、骏景小学配套"   # 单次：自动追问并输出任务包
  python -m fanrenge.cli --json "写一篇800字的朋友圈文案"                        # 只出 JSON 任务包
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fanrenge.engine import run_once, load_templates  # noqa: E402

DEMOS = [
    ("帮我做一条 90 秒的房产短视频，突出南北通透、骏景小学配套",
     ["面向改善型买家", "高端稳重风"]),
    ("给新店开业写个朋友圈文案，300 字左右",
     ["本地宝妈", "接地气口语风"]),
    ("做一个报名用的落地页，1 个页面就行",
     ["表单能提交姓名电话和想上的时段（少儿篮球体验课）", "周边小区家长"]),
]


def show(r):
    if r['state'] == 'ask':
        print('  普惠AI：%s' % r['question'])
        return
    pkg = r['package']
    print('  ── 任务包（JSON，可直接丢给下游 Agent）──')
    for k in ('版本', '来源', '目标'):
        print('   %s: %s' % (k, pkg[k]))
    print('   匹配: %s' % json.dumps(pkg['匹配'], ensure_ascii=False))
    print('   已知参数: %s' % json.dumps(pkg['已知参数'], ensure_ascii=False))
    print('   分步任务:')
    for s in pkg['分步任务']:
        print('     ' + s)
    print('   限制条件: %s' % '；'.join(pkg['限制条件']))
    print('   验收标准: %s' % '；'.join(pkg['验收标准']))
    print('   输出规范: %s' % '；'.join(pkg['输出规范']))
    print('   下游顺序: %s' % ' → '.join(pkg['下游执行顺序']))
    if pkg['待下游确认（可选）']:
        print('   模板自动补齐(可选): %s' % json.dumps(pkg['待下游确认（可选）'], ensure_ascii=False))


def main():
    args = sys.argv[1:]
    tpls = load_templates()
    print('普惠AI 引擎B · 模板库: %d 个模板 ｜ 三级目录: %s'
          % (len(tpls['templates']), '、'.join(tpls['三级目录'].keys())))

    if '--demo' in args:
        ok = 0
        for i, (u, ans) in enumerate(DEMOS, 1):
            print('\n══ 演示 %d ══' % i)
            print('  用户：%s' % u)
            r = run_once(u, ans)
            # 交互式回放，展示追问过程
            from fanrenge.engine import Session
            s = Session()
            r2 = s.start(u)
            print('  普惠AI：%s' % r2['question'])
            for a in ans:
                if r2['state'] != 'ask':
                    break
                print('  用户：%s' % a)
                r2 = s.answer(a)
                if r2['state'] == 'ask':
                    print('  普惠AI：%s' % r2['question'])
            if r2['state'] == 'done':
                print('  普惠AI：信息齐了，任务包已经生成 👇')
                show(r2)
                ok += 1
        print('\n══ 结果: %d/%d 个行业跑通完整闭环 ══' % (ok, len(DEMOS)))
        return 0 if ok == len(DEMOS) else 1

    text = ' '.join(a for a in args if not a.startswith('--'))
    if not text:
        print('用法: python -m fanrenge.cli --demo | "你的大白话需求" [--json]')
        return 2
    r = run_once(text, [])
    if r['state'] == 'ask':
        print('普惠AI：%s' % r['question'])
        print('（把回答作为参数再跑一次，或使用 Session 交互）')
        return 0
    if '--json' in args:
        print(json.dumps(r['package'], ensure_ascii=False, indent=1))
    else:
        show(r)
    return 0


if __name__ == '__main__':
    sys.exit(main())
