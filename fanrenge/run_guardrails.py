# -*- coding: utf-8 -*-
"""普惠AI 期D：回归护栏——任何入库/升级动作前后都跑这一套；任一不过 → 退出码 1

包含：
  1) 引擎测试 test_engine.py
  2) 自学习测试 test_autolearn.py
  3) 草案生成器测试 test_pack_draft.py
  4) 覆盖度核对 verify_coverage_v2.py（旧包内容无归属必须为 0）
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TRANS = os.path.dirname(HERE)
PY = sys.executable


def run(title, args, must_contain=None, cwd=None):
    try:
        r = subprocess.run([PY] + args, capture_output=True, text=True, timeout=900, cwd=cwd or TRANS)
        out = (r.stdout or '') + (r.stderr or '')
        tail = [l for l in out.strip().splitlines() if l.strip()][-1:] or ['']
        ok = (r.returncode == 0)
        if ok and must_contain and must_contain not in out:
            ok = False
            tail = ['缺少必须的输出标记：%s' % must_contain]
        print('%-26s %s   %s' % (title, '✅ 通过' if ok else '❌ 未通过', tail[0][:70]))
        return ok
    except Exception as e:
        print('%-26s ❌ 异常 %s' % (title, str(e)[:60]))
        return False


def main():
    checks = []
    checks.append(run('引擎测试',
                      [os.path.join(TRANS, 'tests_fanrenge', 'test_engine.py')],
                      must_contain='失败 0'))
    checks.append(run('自学习测试',
                      [os.path.join(TRANS, 'tests_fanrenge', 'test_autolearn.py')],
                      must_contain='失败 0'))
    pd = os.path.join(TRANS, 'tests_fanrenge', 'test_pack_draft.py')
    if os.path.isfile(pd):
        checks.append(run('草案生成器测试', [pd], must_contain='失败 0'))
    cov = r'D:\hermes-storage\ai_comm\verify_coverage_v2.py'
    if os.path.isfile(cov):
        checks.append(run('覆盖度核对', [cov], must_contain='无归属 0'))

    ok = all(checks) and bool(checks)
    print('\n回归护栏结果：%s（%d/%d）' % ('✅ 全部通过' if ok else '❌ 有未通过项', sum(checks), len(checks)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
