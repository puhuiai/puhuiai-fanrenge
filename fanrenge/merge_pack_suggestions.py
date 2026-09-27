# -*- coding: utf-8 -*-
"""merge_pack_suggestions.py — 把 packs_suggest/ 的**行业特有**增量建议合并进 templates.json

纪律：
  · 人类已审核（老板 2026-09-27 授权执行）——本脚本即"人审后的落库动作"
  · 只写**差异**：模具通用项（交付物完整/留两类证据/换环境可复现/信息不全、工具没有、方向不对）一律跳过
  · 已存在的条目按去重跳过；写库前备份 templates.json
用法：python merge_pack_suggestions.py [--apply]
"""
import datetime
import io
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, 'templates.json')
SUG = os.path.join(HERE, 'packs_suggest')

GENERIC = [
    '交付物完整可用', '至少留两类证据', '换个环境按步骤能复现',
    '信息不全/没材料', '工具没有或不可用', '做完发现方向不对',
]


def is_generic(s):
    return any(g in s for g in GENERIC)


def main():
    apply_ = '--apply' in sys.argv
    t = json.load(io.open(TPL, encoding='utf-8'))
    changed = []

    for fn in sorted(os.listdir(SUG)):
        if not fn.endswith('.json'):
            continue
        s = json.load(io.open(os.path.join(SUG, fn), encoding='utf-8'))
        ind = s['行业']
        pack = t['_行业包'].get(ind)
        if not pack:
            print('!! 行业包不存在:', ind)
            continue
        print('== %s ==' % ind)
        # 验收
        cur = pack.setdefault('acceptance_extra', [])
        for item in s.get('验收候选', []):
            if is_generic(item):
                continue
            if item in cur:
                print('   验收 已存在，跳过:', item[:40])
                continue
            print('   验收 +新增:', item[:60])
            cur.append(item)
            changed.append((ind, 'acceptance_extra', item))
        # 预案
        pre = pack.setdefault('预案', [])
        for item in s.get('预案候选', []):
            if is_generic(item):
                continue
            if item in pre:
                print('   预案 已存在，跳过:', item[:40])
                continue
            print('   预案 +新增:', item[:60])
            pre.append(item)
            changed.append((ind, '预案', item))

    print('\n共新增 %d 条（行业特有）' % len(changed))
    if not apply_:
        print('(dry-run；加 --apply 落库)')
        return 0

    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = os.path.join(HERE, '_bak_suggest_merge_%s' % ts)
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(TPL, os.path.join(bak, 'templates.json'))
    io.open(TPL, 'w', encoding='utf-8', newline='').write(
        json.dumps(t, ensure_ascii=False, indent=2))
    print('✅ 已落库，备份:', bak)
    print('   复核 _行业包 条数 =', len(t['_行业包']))
    for ind in ('短视频', '网页小程序', '文案写作'):
        p = t['_行业包'][ind]
        print('   %-8s acceptance_extra=%d  预案=%d' % (ind, len(p.get('acceptance_extra', [])), len(p.get('预案', []))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
