# -*- coding: utf-8 -*-
"""cleanup_candidates.py — 清候选池里「已入库」与「碎片」条目（人审后执行，带备份）

判定（两条，全部可解释）：
  ① 已在库（名字出现在 templates.json 的 _行业包 里）⇒ 再挂候选没意义
  ② 大类为空 且 次数 ≤ 1 ⇒ 明显是切碎的片段（如「帮宠物殡」出自「帮宠物殡葬店做…」）

用法：python fanrenge/cleanup_candidates.py [--dry|--apply]
"""
import datetime
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PENDING = os.path.join(HERE, 'pending_templates.json')
TPL = os.path.join(HERE, 'templates.json')


def main():
    apply_ = '--apply' in sys.argv
    d = json.load(io.open(PENDING, encoding='utf-8'))
    t = json.load(io.open(TPL, encoding='utf-8'))
    lib = set(t.get('_行业包', {}).keys())
    pool = d.get('行业候选') or {}

    keep, drop = {}, []
    for k, v in pool.items():
        n = v.get('次数', 0) if isinstance(v, dict) else 0
        cat = (v.get('大类') or '') if isinstance(v, dict) else ''
        if k in lib:
            drop.append((k, '已在库（%s）' % '、'.join(sorted(lib & {k})) or '已在库'))
        elif not cat and n <= 1:
            drop.append((k, '碎片（大类空 + 次数 %d）' % n))
        else:
            keep[k] = v

    print('候选池原有 %d 条' % len(pool))
    for k, why in drop:
        print('   - 清掉 %-10s 原因: %s' % (k, why))
    print('   保留 %d 条: %s' % (len(keep), '、'.join(keep) or '(空)'))

    if not apply_:
        print('\n(dry-run；加 --apply 落盘)')
        return 0

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(HERE, '_bak_cand_clean_%s' % ts)
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(PENDING, os.path.join(bak, 'pending_templates.json'))
    d['行业候选'] = keep
    io.open(PENDING, 'w', encoding='utf-8', newline='').write(
        json.dumps(d, ensure_ascii=False, indent=2))
    print('✅ 已落盘，备份:', bak)
    chk = json.load(io.open(PENDING, encoding='utf-8'))
    print('   复核：候选 %d 条 ｜ pending %d 条 ｜ rejected %d 条'
          % (len(chk.get('行业候选', {})), len(chk.get('pending', [])), len(chk.get('rejected', []))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
