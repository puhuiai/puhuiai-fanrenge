# -*- coding: utf-8 -*-
"""普惠AI 期B/期D：行业包草案生成器 + 质量门禁 + 人审入库 + 增量升级候选

设计铁律（延续项目纪律）
  · AI 只出草案，**绝不自动入库**；入库必须人工执行 approve（并默认跑回归护栏）
  · 草案不得照抄模具句子（自动质检会打回）
  · 归纳「只写差异」：模具管的通用项不重复写进行业包
  · 失败绝不阻断主链路（引擎侧调用一律 try/except）

用法（命令行）
  python pack_draft.py list                  # 看候选池（次数/是否 ready）
  python pack_draft.py gen [--llm] [--all]   # 为 ready 的候选生成行业包草案（写 packs_draft/）
  python pack_draft.py check <行业名>         # 质检草案（不通过会列出原因）
  python pack_draft.py approve <行业名> [--no-guard]   # 人审入库（备份 + 迁移脚本同步 + 回归护栏）
  python pack_draft.py suggest               # 看自动升级建议（packs_suggest/）
  python pack_draft.py clean                 # 清掉候选池里的噪声条目
"""
import io
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from fanrenge import engine as E                                    # noqa: E402

TPL = E.TPL_FILE
PENDING = E.PENDING_FILE
DRAFT_DIR = os.path.join(HERE, 'packs_draft')
SUGGEST_DIR = os.path.join(HERE, 'packs_suggest')
BACKUP_DIR = os.path.join(HERE, 'packs_backup')

# ── 噪声词（候选池卫生）：这些词不能当行业名 ─────────────────────────
NOISE = ('做点东西', '帮我', '随便', '今天', '明天', '天气', '什么', '一个', '一份', '一套',
         '这个', '那个', '怎样', '怎么', '可以', '需要', '想要', '来个', '弄个', '搞个', '写个',
         '做一', '来一', '我', '你', '他', '你好', '谢谢', '测试', '试试', '下的', '上的')

# ── 业务后缀：用来从大白话里抠出「业务主体」当行业名 ────────────────
BIZ_SUFFIX = ('店', '馆', '站', '所', '公司', '中心', '工作室', '医院', '诊所', '学校', '基地',
              '园区', '农庄', '营地', '驿站', '超市', '餐厅', '烘焙', '花店', '旅行社', '中介',
              '事务所', '工厂', '商城', '门店', '集团', '机构', '平台', '品牌', '铺子', '车行',
              '健身房', '幼儿园', '养老院', '培训班', '摄影', '婚庆', '维修')

# ── 大类规范（期B 规则版草案的差异来源）────────────────────────────
BIGMAP = {
    '内容创作': {
        '工具': [{"名": "AI 文案/图像工具", "用途": "出初稿（人工定稿把关）", "没有时": "先出纯文字版，配图后补"}, {"名": "平台规格表", "用途": "按平台规格导出（竖屏/横屏、字数/时长上限）", "没有时": "按平台公开规则人工核对一遍"}],
        '合规': ['AI 生成内容须按规范做明显标识', '不得使用未授权的他人素材/肖像'],
        '自测': ['成品在目标平台真实预览一次（手机+桌面）并截图'],
        'detail': ['先定选题与受众，再动笔', '标题与开头 3 秒内给出钩子', '一篇只讲一件事，别贪多'],
    },
    '电商零售': {
        '工具': [{"名": "电商作图工具", "用途": "做主图/详情页", "没有时": "用现有素材拼图并标注「待补拍」"}, {"名": "商品资料表", "用途": "对齐价格规格与卖点", "没有时": "按现有资料先出草案，缺项标出来"}],
        '合规': ['不得虚假宣传/使用绝对化用语', '价格与库存以实际为准，不承诺无法兑现的优惠'],
        '自测': ['主图/详情页在手机端真实预览并截图', '把价格与规格逐条对照商品资料表'],
        'detail': ['卖点按「用户关心顺序」排，不按内部参数排', '每条卖点配一句人话解释'],
    },
    '技术开发': {
        '工具': [{"名": "代码编辑器 + Claude Code", "用途": "写代码与自测（本机 18081 桥，$0）", "没有时": "先出可运行的骨架 + 说明"}, {"名": "git", "用途": "每次改动提交留痕", "没有时": "退化为文件级改动记录（写清改了哪些文件）"}],
        '合规': ['不得引入未经许可的第三方代码/密钥', '日志与示例数据不得含真实个人信息'],
        '自测': ['跑测试（node --test "tests/*.test.js" / pytest）并把原始输出贴出来', '用浏览器打开页面并截图'],
        'detail': ['改完必 commit，commit 说明写清改了什么', '先让测试红再修绿，不许删测试放宽断言'],
    },
    '生活服务': {
        '工具': [{"名": "服务项目表 + 门店资料", "用途": "把服务写成客户能看懂的项目清单", "没有时": "先用现有信息出草案，缺项标出来"}],
        '合规': ['不得承诺效果/疗效', '涉及价格与退改须写清规则'],
        '自测': ['用真实客户会问的 3 个问题自查一遍答复是否清楚'],
        'detail': ['按「客户到店前→到店中→离店后」三段写', '每条服务写清：给谁、多久、含什么、多少钱'],
    },
    '教育培训': {
        '工具': [{"名": "课标/教材 + 课件工具", "用途": "出大纲与讲义", "没有时": "先出大纲与讲义草稿，标注待补素材"}],
        '合规': ['不得使用未授权的教材原文与考题', '不得做升学/提分承诺'],
        '自测': ['让一个非本专业的人读一遍，看能否看懂'],
        'detail': ['先定学完能做什么，再排知识点', '每节课配一个可检查的练习'],
    },
    '医疗健康': {
        '工具': [{"名": "权威科普资料 + 审核清单", "用途": "确保每个结论有出处", "没有时": "只做常识性内容并标「待医学审核」"}],
        '合规': ['不做诊断/治疗建议，不替代就医', '不得夸大疗效或宣传未经证实的疗法'],
        '自测': ['逐条核对结论是否有权威来源支撑'],
        'detail': ['先写适用人群与不适用人群', '每个结论给出处，写不出处的删掉'],
    },
    '法律财税': {
        '工具': [{"名": "现行法规原文 + 模板", "用途": "逐条引用现行条款", "没有时": "先出框架并标「需执业人士复核」"}],
        '合规': ['不构成法律/税务意见，重大事项提示咨询执业人士', '不得帮助规避法律义务'],
        '自测': ['逐条比对引用条款是否为现行有效版本'],
        'detail': ['先写清适用对象与生效前提', '风险点单独列一节，写明后果与应对'],
    },
    '餐饮本地': {
        '工具': [{"名": "菜品/服务清单 + 门店信息", "用途": "写清位置/时间/价格三件套", "没有时": "先用现有信息出草案，缺项标出来"}],
        '合规': ['食品相关表述不得虚假宣传', '明码标价，不写"最"字号等违规词'],
        '自测': ['把文案念给一个当地客户听，看是否想下单'],
        'detail': ['写清位置/时间/价格三件套', '优惠规则一句话说清，不留隐藏条件'],
    },
    '默认': {
        '工具': [{"名": "现有资料 + 常用工具", "用途": "先出草案", "没有时": "给出替代路径并标注缺什么"}],
        '合规': ['不得虚构事实与数据', '不得做夸大承诺'],
        '自测': ['交付前自己按验收标准逐条过一遍并留证据'],
        'detail': ['先定产出物形式，再动工', '分步做，每步可检查'],
    },
}


# ───────────────────────── 工具函数 ─────────────────────────
def _jload(p, default=None):
    try:
        with io.open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def _jdump(p, d):
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2))
    os.replace(tmp, p)


def _is_noise(name):
    n = (name or '').strip()
    if not n or len(n) < 2 or len(n) > 8:
        return True
    if n in NOISE:
        return True
    return any(x in n for x in ('帮我', '随便', '做点', '下的', '上的', '一份', '一套'))


def extract_industry_name(text, dic=None):
    """从大白话里抠行业名：词典优先 → 业务后缀正则 → 兜底空"""
    g = E.guess_industry(text or '', path=None)
    if g:
        return g[0]['行业'], g[0].get('大类') or ''
    for m in re.finditer(r'([\u4e00-\u9fff]{2,4}?)(' + '|'.join(BIZ_SUFFIX) + r')', text or ''):
        cand = re.sub(r'^(帮我|给我|帮我给|帮|给|为|替|做一个|做一|做|写|弄|搞)+', '', m.group(1)) + m.group(2)
        if not _is_noise(cand):
            return cand, ''
    return '', ''


def mold_texts(templates=None):
    """模具里所有文本（用于「不得照抄模具」质检）"""
    tpls = templates or E.load_templates()
    mdl = tpls.get('_模具') or {}
    out = set()
    for k, v in mdl.items():
        if isinstance(v, list):
            out.update(str(x) for x in v)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, list):
                    out.update(str(x) for x in vv)
                elif isinstance(vv, str):
                    out.add(vv)
    return {t for t in out if len(t) >= 6}


def _dedup(seq):
    out = []
    for x in seq or []:
        if x and x not in out:
            out.append(x)
    return out


# ───────────────────────── 期B：规则版草案生成 ─────────────────────────
def draft_pack(industry, big='', words=None, samples=None, templates=None, use_llm=False):
    """为一个（候选池里的）行业生成行业包草案。规则版；use_llm=True 时尝试大模型润色差异内容"""
    tpls = templates or E.load_templates()
    big = big or ''
    spec = BIGMAP.get(big) or BIGMAP['默认']
    words = _dedup(list(words or []) + [industry])[:10]
    samples = list(samples or [])

    pack = {
        '说明': '自动生成的行业包草案（来源：规则版%s）——入库前请人工复核差异内容' % ('+大模型' if use_llm else ''),
        'tools': [dict(t) for t in spec['工具']],
        'detail_rules': list(spec['detail']),
        'acceptance_extra': [
            '产出物覆盖「%s」的核心场景，且用户拿到就能直接照做' % industry,
            '交付前按本包「自测手段」逐条自查并留证据',
        ],
        'steps_extra': {'前置': ['先确认「%s」这个行业的硬约束（资质/合规/口径）' % industry],
                        '中段': [], '后置': []},
        'slots_extra': ['行业特有的关键信息（如资质、档期、价格口径）'],
        'compliance': list(spec['合规']),
        'downstream_extra': ['%s 专业人员复核' % industry],
        '自测手段': list(spec['自测']),
        '预案': ['行业资料不全 → 先用现有信息出草案，把缺的项标出来',
                 '涉及资质/价格/承诺 → 先说明风险点，不擅自拍板'],
        'match': words,
        '来源': 'AI草案(规则版%s)' % ('+大模型' if use_llm else ''),
        '版本': 1,
        '审核': '待人工',
        '关联大类': big,
        '样例话术': samples[:3],
        '生成时间': time.strftime('%F %T'),
    }
    if use_llm:
        try:
            from fanrenge import pack_draft_llm as L
            pack = L.enrich(pack, industry, big, samples)
            pack['来源'] = 'AI草案(规则版+大模型)'
        except Exception as e:
            pack['llm_note'] = '大模型润色不可用，已回落规则版：%s' % str(e)[:80]
    return pack


# ───────────────────────── 质量门禁 ─────────────────────────
STRONG = set(getattr(E, '_STRONG_KEYS', ()) or ())
MIN_MATCH = 4


def generic_keys():
    """泛词表（数据/内容/设计/文案…）——这些词不能当行业实义词"""
    return set(getattr(E, '_GENERIC_KEYS', ()) or ())


def quality_gate(pack, templates=None, industry=None):
    """6 条门禁 + 照抄检测。返回 (通过?, [问题...])"""
    tpls = templates or E.load_templates()
    bad = []
    mold = mold_texts(tpls)
    ind = industry or (pack.get('match') or [''])[0]

    # ① 不得照抄模具句子
    copied = [x for x in (pack.get('tools', []) + pack.get('detail_rules', []) + pack.get('compliance', [])
                          + pack.get('acceptance_extra', []) + list(pack.get('自测手段') or [])
                          + list(pack.get('预案') or []))
              if str(x) in mold]
    if copied:
        bad.append('照抄模具句子 %d 条：%s' % (len(copied), copied[0][:30]))

    # ② match ≥4 词，且至少 2 个「实义词」（非泛词）——泛词多了归类会抢不过别人
    mt = [str(w) for w in (pack.get('match') or [])]
    generic = generic_keys()
    real = [w for w in mt if len(w) >= 2 and w not in generic]
    if len(mt) < MIN_MATCH:
        bad.append('match 只有 %d 个词（要求 ≥%d）' % (len(mt), MIN_MATCH))
    if len(real) < 2:
        bad.append('match 里实义词不足（至少 2 个非泛词词条，否则归类抢不过别的行业）')

    # ③ tools ≥1 且带「没有时」替代路径
    tools = pack.get('tools') or []
    if len(tools) < 1:
        bad.append('没有写任何工具')
    elif not any(('没有时' in json.dumps(x, ensure_ascii=False)) or ('替代' in json.dumps(x, ensure_ascii=False))
                 for x in tools):
        bad.append('工具没写「没有时」的替代路径')

    # ④ 行业验收 ≥2
    if len(pack.get('acceptance_extra') or []) < 2:
        bad.append('行业验收少于 2 条')

    # ⑤ 合规 ≥1
    if len(pack.get('compliance') or []) < 1:
        bad.append('没有行业合规提醒（红线缺位）')

    # ⑥ 预案 ≥1
    if len(pack.get('预案') or []) < 1:
        bad.append('没有应变预案')

    # ⑦ 行业名卫生（不能是噪声词）
    if _is_noise(ind):
        bad.append('行业名疑似噪声词：%s' % ind)

    return (not bad), bad


# ───────────────────────── 候选池 → 草案 ─────────────────────────
def list_candidates(pending_path=None):
    d = _jload(pending_path or PENDING)
    return d.get('行业候选') or {}


def clean_candidates(pending_path=None, dry=False):
    """清掉候选池里的噪声条目（如「做点东西」「帮我给楼」）"""
    p = pending_path or PENDING
    d = _jload(p)
    pool = d.get('行业候选') or {}
    keep, drop = {}, []
    for k, v in pool.items():
        if _is_noise(k):
            drop.append(k)
        else:
            keep[k] = v
    if not dry:
        d['行业候选'] = keep
        _jdump(p, d)
    return keep, drop


def generate_drafts(pending_path=None, out_dir=None, only_ready=True, use_llm=False, templates=None):
    """为候选池里 ready 的行业生成草案文件（写磁盘，不入库）"""
    out = out_dir or DRAFT_DIR
    os.makedirs(out, exist_ok=True)
    tpls = templates or E.load_templates()
    made, skipped = [], []
    for name, rec in list_candidates(pending_path).items():
        if _is_noise(name):
            skipped.append((name, '噪声词'))
            continue
        if only_ready and not rec.get('ready'):
            skipped.append((name, '次数不足(%s)' % rec.get('次数')))
            continue
        pack = draft_pack(name, rec.get('大类') or '', rec.get('命中词'), rec.get('样例话术'), tpls,
                          use_llm=use_llm)
        ok, issues = quality_gate(pack, tpls, name)
        pack['质检'] = {'通过': ok, '问题': issues}
        _jdump(os.path.join(out, '%s.json' % name), pack)
        made.append((name, ok, issues))
    return made, skipped


def approve_pack(name, templates_path=None, draft_dir=None, do_guard=True, guard_cmd=None):
    """人审入库：备份 → 写入 _行业包（带 来源/版本/审核）→ 跑回归护栏"""
    tp = templates_path or TPL
    dd = draft_dir or DRAFT_DIR
    src = os.path.join(dd, '%s.json' % name)
    if not os.path.isfile(src):
        return False, ['找不到草案文件：%s' % src]
    pack = _jload(src)
    tpls = E.load_templates(tp)
    ok, issues = quality_gate(pack, tpls, name)
    if not ok:
        return False, ['质检未通过：' + '；'.join(issues)]

    os.makedirs(BACKUP_DIR, exist_ok=True)
    shutil.copy2(tp, os.path.join(BACKUP_DIR, 'templates.json.bak_before_%s_%s'
                                  % (re.sub(r'[^\w\u4e00-\u9fff]', '_', name), time.strftime('%Y%m%d_%H%M%S'))))
    stored = {k: v for k, v in pack.items() if k not in ('质检', 'llm_note', '样例话术', '关联大类')}
    stored['来源'] = pack.get('来源') or 'AI草案'
    stored['审核'] = '人工审核通过 %s' % time.strftime('%F')
    stored['版本'] = int(pack.get('版本') or 1)
    tpls.setdefault('_行业包', {})[name] = stored
    _jdump(tp, tpls)

    msgs = ['已入库：_行业包[%s]（来源 %s）' % (name, stored['来源'])]
    # 同步迁移脚本的提示（可复现性）
    try:
        mig = os.path.join(os.path.dirname(HERE), '..', '..', '..', '..', 'hermes-storage', 'ai_comm',
                           'migrate_fanrenge_mold.py')
        if os.path.isfile(mig):
            msgs.append('提示：迁移脚本未包含新包，重跑会覆盖（已备份，注意）')
    except Exception:
        pass
    if do_guard:
        g = guard_cmd or [sys.executable, os.path.join(HERE, 'run_guardrails.py')]
        try:
            import subprocess
            r = subprocess.run(g, capture_output=True, text=True, timeout=600)
            tail = (r.stdout or '').strip().splitlines()[-1:] or ['']
            msgs.append('回归护栏：%s（%s）' % ('通过' if r.returncode == 0 else '未通过', tail[0][:60]))
            if r.returncode != 0:
                msgs.append('⚠️ 护栏未通过——建议回滚（备份在 %s）' % BACKUP_DIR)
                return False, msgs
        except Exception as e:
            msgs.append('回归护栏执行异常（不阻断）：%s' % str(e)[:60])
    return True, msgs


# ───────────────────────── 期D：增量升级候选 ─────────────────────────
def upgrade_candidates_from_task(pkg, out_dir=None):
    """任务完成后：把这次任务里「新出现的」约束/验收/坑登记为升级建议（不自动入库）"""
    out = out_dir or SUGGEST_DIR
    try:
        ind = ((pkg or {}).get('匹配') or {}).get('行业') or ''
        if not ind or ind == '通用':
            return None
        os.makedirs(out, exist_ok=True)
        f = os.path.join(out, '%s.json' % ind)
        prev = _jload(f, {}) or {}
        add = {}
        for k_src, k_dst in (('必须守的规矩', '合规候选'), ('验收标准', '验收候选'), ('应变预案（行业标准）', '预案候选')):
            cur = prev.get(k_dst) or []
            new = [x for x in (pkg.get(k_src) or []) if x and x not in cur]
            add[k_dst] = _dedup(cur + new)
        rec = {'行业': ind, '更新': time.strftime('%F %T'), '来源': '自动升级建议（需人工审核）',
               '本次任务': (pkg.get('目标') or '')[:60], **add}
        _jdump(f, rec)
        return f
    except Exception:
        return None


def list_suggestions(out_dir=None):
    out = out_dir or SUGGEST_DIR
    if not os.path.isdir(out):
        return {}
    return {os.path.splitext(f)[0]: _jload(os.path.join(out, f)) for f in os.listdir(out) if f.endswith('.json')}


# ───────────────────────── CLI ─────────────────────────
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'list'

    if cmd == 'list':
        pool = list_candidates()
        if not pool:
            print('候选池为空')
        for k, v in pool.items():
            print('  %-12s %s 次  ready=%-5s 命中词=%s' % (k, v.get('次数'), v.get('ready'),
                                                         '/'.join((v.get('命中词') or [])[:4])))
        return 0

    if cmd == 'clean':
        keep, drop = clean_candidates(dry='--dry' in argv)
        print('保留 %d 个：%s' % (len(keep), '、'.join(keep)))
        print('清掉 %d 个噪声：%s' % (len(drop), '、'.join(drop)))
        return 0

    if cmd == 'gen':
        use_llm = '--llm' in argv
        only_ready = '--all' not in argv
        made, skipped = generate_drafts(only_ready=only_ready, use_llm=use_llm)
        print('生成草案 %d 个（目录 %s）' % (len(made), DRAFT_DIR))
        for name, ok, issues in made:
            print('  %-12s 质检 %s %s' % (name, '✅通过' if ok else '❌未过', '' if ok else '｜' + '；'.join(issues)))
        for name, why in skipped:
            print('  %-12s 跳过（%s）' % (name, why))
        return 0

    if cmd == 'check':
        if len(argv) < 2:
            print('用法：check <行业名>')
            return 2
        name = argv[1]
        pack = _jload(os.path.join(DRAFT_DIR, '%s.json' % name))
        if not pack:
            print('找不到草案：%s' % name)
            return 2
        ok, issues = quality_gate(pack, industry=name)
        print('%s：%s' % (name, '✅ 质检通过' if ok else '❌ 未通过'))
        for i in issues:
            print('   -', i)
        return 0 if ok else 1

    if cmd == 'approve':
        if len(argv) < 2:
            print('用法：approve <行业名> [--no-guard]')
            return 2
        ok, msgs = approve_pack(argv[1], do_guard='--no-guard' not in argv)
        for m in msgs:
            print('  ', m)
        return 0 if ok else 1

    if cmd == 'suggest':
        s = list_suggestions()
        if not s:
            print('暂无升级建议')
        for k, v in s.items():
            print('  %-12s 更新 %s ｜ 合规候选 %d / 验收候选 %d / 预案候选 %d'
                  % (k, v.get('更新'), len(v.get('合规候选') or []), len(v.get('验收候选') or []),
                     len(v.get('预案候选') or [])))
        return 0

    print(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main())
