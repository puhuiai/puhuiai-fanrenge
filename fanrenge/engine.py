# -*- coding: utf-8 -*-
"""普惠AI · 引擎B（原生主管智能体）— 零算力规则引擎

定位（对齐文档 149–197 行结论）：
  普惠AI = 一套「口语需求 → 标准化 AI 任务工作流」的可嵌入**规则技能包**。
  它本身不是大模型、不消耗算力：需求分类、模板匹配、追问补全、任务包组装全部是确定性规则；
  宿主智能体（小龙虾 / Hermes / 任意 Agent）负责"说话"，普惠AI负责"定流程、定校验、定结构"。

四层（文档 7–34 行）：
  L1 口语入口 → L2 行业模板库(行业→场景→任务) → L3 主管智能体(识别/匹配/追问/组装) → L4 任务下发包
引擎B 与引擎A 的分工（文档 80–103 行）：
  B = 从零拆解创造（免费、核心、本文件）；A = 付费行业模板库（候选增强，可选）
"""
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TPL_FILE = os.path.join(HERE, 'templates.json')

# ── v1.1 综合模具 + 行业标准（模板库的 _模具 / _行业包 两段）────────────
MOLD_KEY = '_模具'
PACK_KEY = '_行业包'
_STEP_NUM = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'
_LEAD = re.compile(r'^[\s]*[①-⑳0-9]{1,2}\s*[.、)）]?\s*')


def load_mold(templates=None):
    """取综合模具（所有任务统一套用）；老库没有 _模具 段时返回 {}（向后兼容）"""
    t = templates if templates is not None else load_templates()
    return dict((t or {}).get(MOLD_KEY) or {})


def _pack_of(templates, industry):
    """按行业取行业标准包：先精确匹配包名，再匹配包的「适用行业」列表"""
    packs = (templates or {}).get(PACK_KEY) or {}
    if not industry:
        return {}, None
    if industry in packs:
        return packs[industry], industry
    for name, p in packs.items():
        if industry in (p.get('适用行业') or []):
            return p, name
    return {}, None


def _subdomain_of(pack, tpl, text):
    """子域（行业>子域）：模板显式声明优先，否则按子域关键词命中用户原话"""
    subs = (pack or {}).get('_子域') or {}
    name = (tpl or {}).get('子域')
    if name and name in subs:
        return subs[name], name
    for n, sp in subs.items():
        for kw in (sp.get('match') or []):
            if kw and kw in (text or ''):
                return sp, n
    return {}, None


def _dedup(seq):
    """去重保序（空值丢掉）；dict 也支持（问法表用）"""
    out = []
    for x in seq or []:
        if x is None:
            continue
        if isinstance(x, dict):
            if x not in out:
                out.append(x)
        else:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
    return out


def _renumber(steps):
    """统一步骤编号：剥掉原有 ①②③/1. 前缀，按顺序重编号"""
    out = []
    for i, s in enumerate(steps or []):
        t = _LEAD.sub('', str(s)).strip()
        if not t:
            continue
        out.append('%s %s' % (_STEP_NUM[i] if i < len(_STEP_NUM) else '·', t))
    return out


def _insert_after(steps, anchor, items, log=None, label=''):
    """把 items 插到「含 anchor 的那一步」之后；找不到锚点 → 追加末尾并记日志（绝不抛异常）"""
    items = [x for x in (items or []) if x]
    if not items:
        return list(steps)
    idx = [i for i, s in enumerate(steps) if anchor and anchor in str(s)]
    if not idx:
        if log is not None:
            log.append('锚点「%s」未找到，%s内容已追加到末尾' % (anchor, label))
        return list(steps) + list(items)
    at = idx[0] + 1
    return list(steps[:at]) + list(items) + list(steps[at:])


def _merge_two_pack(a, b):
    """合并两个行业包（a 在前、b 在后；列表去重保序，steps_extra 按锚点分别合并）"""
    a, b = dict(a or {}), dict(b or {})
    out = dict(a)
    for k, v in b.items():
        if k in ('steps_extra',):
            cur = dict(out.get(k) or {})
            for ak, av in (v or {}).items():
                cur[ak] = _dedup(list(cur.get(ak) or []) + list(av or []))
            out[k] = cur
        elif isinstance(v, list):
            out[k] = _dedup(list(out.get(k) or []) + list(v))
        else:
            out[k] = v
    return out


def _effective_pack(templates, industry, _depth=0):
    """取**生效**的行业包：自身 + 「继承」的共享包（如 网页小程序/基础APP开发 继承 编程开发）
    继承包的内容排在前面（基础在前），自身差异排后面。"""
    p, name = _pack_of(templates, industry)
    if not p or _depth > 3:
        return p, name
    bases = p.get('继承') or []
    if not bases:
        return p, name
    base_merged = {}
    for b in bases:
        bp, _bn = _effective_pack(templates, b, _depth + 1)
        base_merged = _merge_two_pack(base_merged, bp)
    return _merge_two_pack(base_merged, p), name


def _guess_pack(tpls, text, min_hits=1):
    """自由模式按关键词猜行业包（用每个包的 match 打分）
    —— 让「自动学出来的新行业包」入库后立刻能用；命中太少就不猜，避免乱套标准。"""
    low = (text or '').lower()
    best, bs, bname = {}, 0, ''
    for name, p in (tpls.get(PACK_KEY) or {}).items():
        if '不直接挂' in str(p.get('说明') or ''):      # 共享基础包（如 编程开发）不参与直接猜
            continue
        hits = sum(1 for w in (p.get('match') or []) if str(w).lower() in low)
        if hits > bs:
            eff, _n = _effective_pack(tpls, name)
            best, bs, bname = eff, hits, name
    if bs >= min_hits:
        return best, bname
    return {}, ''


def merge_pack(tpl, text='', templates=None, cls=None):
    """v1.1 核心拼接：模具 ∪ 行业标准 ∪ 子域 ∪ 场景差异 → 五组内容（确定性规则，不调模型）

    返回: steps / questions / rules / acceptance / output_spec / downstream
          / 行业包 / 子域 / 工具 / 合规 / log / 模具版本
    """
    tpls = templates if templates is not None else load_templates()
    mold = load_mold(tpls)
    tpl = tpl or {}
    industry = tpl.get('industry') or (cls or {}).get('industry') or ''
    pack, pack_name = _effective_pack(tpls, tpl.get('行业包') or industry)
    if not pack_name and not tpl.get('industry'):        # 自由模式：按行业包关键词猜（期A/期B 让新包立刻可用）
        pack, pack_name = _guess_pack(tpls, text)
    sub, sub_name = _subdomain_of(pack, tpl, text)
    log = []
    ex = (pack.get('steps_extra') or {})
    pre, mid, post = list(ex.get('前置') or []), list(ex.get('中段') or []), list(ex.get('后置') or [])
    ach = (mold.get('锚点') or {})

    steps = list(mold.get('steps_base') or [])
    steps = _insert_after(steps, ach.get('前置', '环境'), pre, log, '行业前置')
    steps += mid                                     # 行业工艺步（排在场景差异之前）
    steps += list(tpl.get('steps') or [])             # 场景差异
    steps += list(mold.get('steps_tail') or [])       # 模具收尾（自检 / 交付复盘）
    steps = _insert_after(steps, ach.get('后置', '自检'), post, log, '行业后置')

    return {
        'steps': steps,
        'questions': _dedup((mold.get('questions_base') or []) + (pack.get('slots_extra') or [])
                            + (sub.get('slots_extra') or [])),
        'rules': _dedup((mold.get('rules_base') or []) + (pack.get('detail_rules') or [])
                        + (sub.get('detail_rules') or []) + (tpl.get('rules') or [])),
        'acceptance': _dedup((mold.get('acceptance_base') or []) + (pack.get('acceptance_extra') or [])
                             + (sub.get('acceptance_extra') or []) + (tpl.get('acceptance') or [])),
        # 下游顺序：模具首项（执行 Agent）在最前，具体执行者随后，收尾（独立复核/复盘）垫底
        'downstream': _dedup((mold.get('downstream_base') or [])[:1]
                             + (tpl.get('downstream') or []) + (pack.get('downstream_extra') or [])
                             + (mold.get('downstream_base') or [])[1:]),
        'output_spec': list(tpl.get('output_spec') or mold.get('output_spec_base') or []),
        # 自测手段（v1.1 补）：执行方拿什么证明「做完了」——视频1「必须给 AI 自测能力」的落地
        '自测手段（行业标准）': list(pack.get('自测手段') or mold.get('自测手段_base') or []),
        '行业包': pack_name, '子域': sub_name,
        '工具': list(pack.get('tools') or []),
        '合规': _dedup((pack.get('compliance') or []) + (sub.get('compliance') or [])),
        '模具版本': mold.get('版本', ''), 'log': log,
        # 应变预案（v1.1 补）：行业差异 + 模具通用兜底——「卡住了怎么办」，来自视频2 的"动态调整"
        '预案': _dedup((pack.get('预案') or []) + (sub.get('预案') or []) + list(mold.get('预案_base') or [])),
    }


# ── 经验台账：前置经验检索（v1.1 补，2026-09-24）─────────────────────
# 纯本地 JSON 台账，零算力：出包前查「同行业/同场景上次是怎么做的」，出包后自动登记一条。
EXP_FILE = os.path.join(HERE, 'experience.json')


def load_experience(path=None):
    try:
        with open(path or EXP_FILE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def recall(industry, scene='', path=None, limit=3):
    """前置经验检索：同行业优先、同场景置顶，返回最近的 limit 条"""
    if not industry:
        return []
    items = list((load_experience(path) or {}).get(industry) or [])
    if not items:
        return []
    same = [x for x in items if scene and x.get('场景') == scene]
    rest = [x for x in items if x not in same]
    return (same + rest)[-limit:][::-1]


def remember(pkg, path=None):
    """出包后登记一条经验（幂等：同行业+同场景+同目标摘要不重复登记）返回 True/False"""
    try:
        ind = ((pkg or {}).get('匹配') or {}).get('行业') or ''
        if not ind or ind == '通用':
            return False
        goal = ((pkg or {}).get('目标') or '')
        fv = (pkg or {}).get('已知参数') or {}
        key = fv.get('主题') or fv.get('主要内容') or fv.get('功能') or ''
        if isinstance(key, str) and key.strip():
            goal = key.strip() + '｜' + goal
        goal = re.sub(r'（待确认）', '', goal).strip()[:60]
        p = path or EXP_FILE
        d = load_experience(p)
        arr = list(d.get(ind) or [])
        if any(x.get('目标摘要') == goal for x in arr):
            return False
        arr.append({'日期': time.strftime('%F'), '场景': ((pkg.get('匹配') or {}).get('场景') or ''),
                    '任务': ((pkg.get('匹配') or {}).get('任务') or ''), '目标摘要': goal,
                    '行业包': ((pkg.get('匹配') or {}).get('行业包') or ''),
                    '步数': len(pkg.get('分步任务') or [])})
        d[ind] = arr[-50:]                      # 每个行业最多留 50 条，防台账膨胀
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, p)
        return True
    except Exception:
        return False                            # 登记失败绝不影响出包


def _exp_lines(industry, scene):
    """给任务包用的「前置经验」行：没有历史时给一句提示，不装懂"""
    if not industry or industry == '通用':
        return ['（自由模式：无同行业历史可参考，本次做完会自动登记一条供下次使用）']
    items = recall(industry, scene)
    if not items:
        return ['（%s 暂无历史任务记录；本次完成后会自动登记，下次同类任务就能看到）' % industry]
    return ['%s %s｜%s' % (x.get('日期', ''), x.get('场景', ''), x.get('目标摘要', '')) for x in items]


# ── 行业词典 + 新行业识别（期A，2026-09-25）───────────────────────────
# 目的：14 个行业包覆盖不了市场 —— 认得的新行业先登记候选池，出现次数够了再生成行业包草案。
INDUSTRY_FILE = os.path.join(HERE, 'industries.json')


def load_industries(path=None):
    try:
        with open(path or INDUSTRY_FILE, encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def industry_vocab(path=None):
    """词典平坦化 → [(行业, 大类, 词)]"""
    d = load_industries(path)
    out = []
    for big, blk in (d.get('大类') or {}).items():
        for ind, words in (blk.get('行业') or {}).items():
            for w in words:
                out.append((ind, big, w))
    return out


def guess_industry(text, limit=3, path=None):
    """从需求里猜行业（词典匹配，零算力）。返回按命中数排序的候选列表"""
    low = (text or '').lower()
    hit = {}
    for ind, big, w in industry_vocab(path):
        if w.lower() in low:
            c = hit.setdefault(ind, {'行业': ind, '大类': big, '命中': []})
            c['命中'].append(w)
    cand = sorted(hit.values(), key=lambda x: (-len(x['命中']), x['行业']))
    for c in cand:
        c['分数'] = len(c['命中'])
    return cand[:limit]


def known_industries(path=None):
    return sorted({i for i, _b, _w in industry_vocab(path)})


def register_candidate(text, industry, big='', words=None, path=None):
    """把「见没见过的新行业」登记进候选池（pending_templates.json 的 行业候选 段）。
    出现次数达到阈值 → ready=True（可以生成行业包草案了）。返回 (次数, ready)"""
    try:
        p = path or PENDING_FILE
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            d = {}
        pool = d.get('行业候选') or {}
        thr = int(((load_industries().get('阈值') or {}).get('候选转正次数')) or 3)
        rec = pool.get(industry) or {'行业': industry, '大类': big or '', '次数': 0, '命中词': [], '样例话术': [],
                                     '首见': time.strftime('%F'), 'ready': False}
        if big and not rec.get('大类'):                 # 补齐大类（先来的不知大类，后来知道了要补上）
            rec['大类'] = big
        key = (text or '')[:80]
        if key and key not in rec['样例话术']:
            rec['样例话术'] = (rec['样例话术'] or [])[-9:] + [key]
        rec['次数'] = int(rec.get('次数') or 0) + 1
        for w in (words or []):
            if w not in (rec.get('命中词') or []):
                rec['命中词'].append(w)
        rec['最近'] = time.strftime('%F')
        rec['ready'] = rec['次数'] >= thr
        pool[industry] = rec
        d['行业候选'] = pool
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=2))
        os.replace(tmp, p)
        return rec['次数'], rec['ready']
    except Exception:
        return 0, False

# ── 通用槽位：跨行业都要问的东西（大白话问法，禁用专业名词）────────────
SLOT_ASK = {
    '时长秒': '这个视频你想做多长？（比如 30 秒 / 60 秒 / 90 秒）',
    '目标受众': '这条内容主要给谁看？（比如刚需家庭、改善型买家、年轻宝妈）',
    '风格': '你想要的风格是接地气口语一点，还是高端专业一点？',
    '卖点数量': '你最想突出的卖点有几个？分别是什么？',
    '投放平台': '发在哪个平台？（抖音 / 视频号 / 小红书 / 公众号 / 官网）',
    '字数': '大概要多少字？（比如 300 字短文案 / 1000 字长文）',
    '页面数量': '需要几个页面？（比如 1 个落地页 / 3 个页面）',
    '技术栈': '有没有指定技术？（没指定我就用最简单通用的做法）',
    '功能点': '这个页面/小程序主要要实现什么功能？（比如报名表单、商品展示、预约）',
    '主题': '你要写的是什么事？（一句大白话就行，比如"新店开业优惠"）',
    '交付物': '最后想要什么形式？（文案 / 脚本+分镜 / 可运行代码 / 全套）',
}

# ── 大白话 → 槽位 的抽取规则（regex，确定性，可测）──────────────────
def _num_cn(s):
    m = re.search(r'(\d+(?:\.\d+)?)\s*(秒|s\b|分钟|分|min)', s, re.I)
    if not m:
        return None
    v = float(m.group(1))
    return int(v * 60) if ('分' in m.group(2).lower() or 'min' in m.group(2).lower()) else int(v)


AUDIENCE_HINTS = ['刚需', '改善', '买家', '宝妈', '学生', '上班族', '家长', '游客', '年轻人',
                  '老年人', '女性', '男性', '企业', '老板', '创业者', '本地', '外地']
STYLE_MAP = {'接地气': '接地气口语风', '口语': '接地气口语风', '土味': '接地气口语风',
             '高端': '高端稳重风', '稳重': '高端稳重风', '专业': '高端稳重风',
             '幽默': '幽默轻松风', '轻松': '幽默轻松风', '正式': '正式规范风'}
PLATFORM_HINTS = ['抖音', '视频号', '小红书', '公众号', 'b站', '快手', '官网', '朋友圈']
SELLPOINT_SPLIT = re.compile(r'[、,，/]')


def extract_slots(text, tpl=None):
    """从一句大白话里抽能抽到的槽位（抽不到的留给追问）"""
    s = text or ''
    out = {}
    n = _num_cn(s)
    if n:
        out['时长秒'] = n
    for a in AUDIENCE_HINTS:
        if a in s:
            out['目标受众'] = a + '家庭' if a in ('刚需', '改善') else a
            break
    for k, v in STYLE_MAP.items():
        if k in s:
            out['风格'] = v
            break
    for p in PLATFORM_HINTS:
        if p.lower() in s.lower():
            out['投放平台'] = p
            break
    m = re.search(r'(\d+)\s*个?\s*(卖点|亮点)', s)
    if m:
        out['卖点数量'] = int(m.group(1))
    m = re.search(r'(\d{2,5})\s*字', s)
    if m:
        out['字数'] = int(m.group(1))
    m = re.search(r'(\d+)\s*个?\s*页面', s)
    if m:
        out['页面数量'] = int(m.group(1))
    m = re.search(r'(突出|主打|强调)[:：]?\s*([^。；;，,\n]{2,60})', s)
    if m:
        pts = [x.strip() for x in SELLPOINT_SPLIT.split(m.group(2)) if x.strip()]
        if pts:
            out['卖点内容'] = pts
            out.setdefault('卖点数量', len(pts))
    # 主题优先：口语里常说"讲/说/介绍/推广 X"，比按产出物名词反推更准
    m2 = re.search(r'(?:讲|说|介绍|推广|宣传|关于|卖)[一下]?\s*([^\s，,。；;]{2,16})', s)
    if m2:
        out['主题'] = m2.group(1)
    # 主题：取产出物名词前的短语（排除"的/空格"，剥掉"帮我做/写个/一个"这类虚词）
    _PLAT = '朋友圈|公众号|抖音|视频号|小红书|快手|官网|网站'
    m = re.search(r'([^\s的，,。；;]{2,12}?)(?:的)?(?:' + _PLAT + r')?'
                  r'(文案|软文|推文|落地页|页面|小程序|网页|短视频|视频)', s)
    if m and '主题' not in out:
        t = re.sub(r'^(帮|给|为|请|我|做|要|想|需要|来|一)+', '', m.group(1))
        t = re.sub(r'^(个|条|份|篇|张)', '', t)
        t = re.sub(r'^(在|到|发到|发在|投放在|投放)?(' + _PLAT + r')', '', t)   # "在抖音"→""
        t = re.sub(r'^(写|做|生成|来|拍|搞)个', '', t)
        t = re.sub(r'(' + _PLAT + r')$', '', t)          # 兜底：万一平台词被吃进来
        t = re.sub(r'(写|做|要|生成|拍|个|条|份|篇|用|的)+$', '', t)
        t = t.strip()
        if len(t) >= 2 and not t.isdigit():      # 拿不准就不填，交给追问（文档 29–30 行）
            out['主题'] = t
    return out


# ── 模板库 ────────────────────────────────────────────────
def load_templates(path=TPL_FILE):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


# 行业归类打分用词表（2026-09-24 修复：句子里出现泛词「数据」就被「数据分析」抢走）
_GENERIC_KEYS = ('数据', '统计', '分析', '内容', '设计', '文案', '视频', '方案', '材料',
                 '客户', '服务', '产品', '计划', '报告', '推广', '话术', '素材', '效果', '活动')
_STRONG_KEYS = ('html', 'h5', '网页', '页面', '单页', '前端', '后端', '小程序', '落地页', '官网',
                '代码', '程序', '脚本', '接口', 'api', '数据库', '部署', 'git', 'excel', 'ppt',
                '表格', '公式', '报表', '合同', '条款', '处方', '教案', '菜品', '菜单')


def _kw_weight(k):
    """关键词权重：强信号词（HTML/页面/代码…）×3；泛词（数据/内容/设计…）×0.4；
    其余按长度（≥3 字 ×2，≤2 字 ×1）——避免「数据」这类泛词压过「页面」这类强信号词。"""
    kl = (k or '').lower()
    if kl in _STRONG_KEYS:
        return 3.0
    if k in _GENERIC_KEYS:
        return 0.4
    return 2.0 if len(k) >= 3 else 1.0


def _score(tpl, text):
    s = 0.0
    low = (text or '').lower()
    for k in tpl.get('match', []):
        if k.lower() in low:
            s += 3 * _kw_weight(k)
    # industry/scene/task 都是字符串（不是列表）——这里统一成列表再遍历，别直接相加
    names = [tpl.get('industry'), tpl.get('scene')] + (tpl.get('task') or '').split()
    for k in names:
        if k and k in (text or ''):
            s += 2
    return s


def classify(text, templates=None):
    """L1→L2：口语 → (行业, 场景, 任务, 置信度)"""
    templates = templates or load_templates()
    best, bs = None, 0
    for t in templates['templates']:
        s = _score(t, text)
        if s > bs:
            best, bs = t, s
    if not best or bs == 0:
        _g = guess_industry(text)
        if _g:
            _c0 = _g[0]
            return {'industry': '通用', 'scene': '自由模式', 'task': '临时任务流',
                    'confidence': 0.3, 'template': None, '新行业候选': _c0,
                    '行业候选列表': _g,
                    'note': '词典认得「%s」（大类：%s），但还没有对应行业包/模板 → 先走自由模式'
                            '（多轮提问搭建临时工作流），同时登记进候选池（够次数就自动出行业包草案）'
                            % (_c0['行业'], _c0.get('大类') or '未分类')}
        return {'industry': '通用', 'scene': '自由模式', 'task': '临时任务流',
                'confidence': 0.2, 'template': None, '新行业候选': None,
                'note': '没有匹配到行业模板，词典里也没有这个行业（自由模式：多轮提问搭建临时工作流）'}
    conf = min(0.98, 0.45 + 0.15 * bs)
    return {'industry': best['industry'], 'scene': best['scene'], 'task': best['task'],
            'confidence': round(conf, 2), 'template': best,
            'note': '按【行业→场景→任务】三级目录命中：%s/%s/%s'
                    % (best['industry'], best['scene'], best['task'])}


# ── L3 主管智能体：追问补全 ────────────────────────────────
def missing_slots(tpl, filled, mold=None, free_mode=False):
    """缺什么问什么。v1.1：模具通用问项追加在最后，且只在自由模式追问
    （命中模板的任务不额外增加追问轮数——用户体感不变）"""
    req = [k for k in (tpl or {}).get('required', []) if k not in filled or filled[k] in (None, '', [])]
    for q in (mold or {}).get('questions_base', []) or []:
        slot, use = q.get('slot'), q.get('适用', '全部')
        if not slot or use == '不追问':
            continue
        if use == '自由模式' and not free_mode:
            continue
        if (slot not in filled or filled[slot] in (None, '', [])) and slot not in req:
            req.append(slot)
    return req


def next_question(tpl, missing, mold=None):
    """永远用大白话问（文档 117–118 行：不问 prompt/角色设定，只问风格等生活语言）"""
    if not missing:
        return None
    k = missing[0]
    ask = dict(SLOT_ASK)
    for q in (mold or {}).get('questions_base', []) or []:
        if q.get('slot') and q.get('问法'):
            ask.setdefault(q['slot'], q['问法'])
    if k in ask:
        return {'slot': k, 'question': ask[k]}
    return {'slot': k, 'question': '还想确认一件事：%s 你希望是什么？' % k}


def _default(tpl, k):
    return (tpl.get('optional_defaults') or {}).get(k)


# ── L4 任务下发包 ─────────────────────────────────────────
def _tool_line(x):
    """工具条目兼容两种写法：dict（名/用途/没有时）与纯文本（自动生成草案可能是文本）"""
    if isinstance(x, dict):
        return '%s：%s；没有时 %s' % (x.get('名') or '', x.get('用途') or '',
                                     x.get('没有时') or '用替代工具先出草案')
    return str(x)


def build_package(text, tpl, filled, cls, templates=None):
    """v1.1：模具 ∪ 行业标准 ∪ 子域 ∪ 场景差异 → 任务包（字段名与 1.0 完全一致）"""
    tpls = templates if templates is not None else load_templates()
    m = merge_pack(tpl, text, tpls, cls)
    free_mode = not tpl
    filled = dict(filled or {})
    if not filled.get('交付形式'):                      # 交付形式不追问：由输出规范自动补
        filled['交付形式'] = '、'.join(m['output_spec']) or '按输出规范交付'
    if not free_mode and not filled.get('完成标准'):     # 命中模板：完成标准由验收标准代填，不追问
        filled['完成标准'] = '满足「验收标准」全部条目（含证据要求）'

    goal_tpl = (tpl or {}).get('goal', '完成用户的口语需求：{original}')
    vals = {k: v for k, v in filled.items() if isinstance(v, (str, int, float))}
    vals['original'] = text
    for _k in re.findall(r'\{(\w+)\}', goal_tpl):      # 缺的槽位不抛 KeyError，标"待确认"
        vals.setdefault(_k, '（待确认）')
    goal = goal_tpl.format(**vals)
    if filled.get('卖点内容'):
        vals['卖点'] = '、'.join(map(str, filled['卖点内容']))

    def _fill(x):
        t = str(x)
        for k, v in vals.items():
            t = t.replace('{%s}' % k, str(v))
        return re.sub(r'\{([^}]{1,12})\}', lambda mm: str(filled.get(mm.group(1), '（待确认）')), t)

    note = '通用模具（未匹配行业）' if free_mode else (cls.get('note', '') or '')
    if m['log']:
        note = (note + '｜' if note else '') + '；'.join(m['log'])
    pkg = {
        '版本': 'fanrenge-engineB/1.1',
        '来源': '引擎B（综合模具 + 行业标准，零算力确定性拼接；模具 %s）' % (m['模具版本'] or '内置'),
        '匹配': {'行业': cls['industry'], '场景': cls['scene'], '任务': cls['task'],
                 '行业包': m['行业包'] or '', '子域': m['子域'] or '',
                 '置信度': cls['confidence'], '说明': note},
        '目标': goal,
        '已知参数': filled,
        '待下游确认（可选）': {k: _default(tpl, k) for k in ((tpl or {}).get('optional', []) or [])
                       if k not in filled and _default(tpl, k) is not None},
        '分步任务': _renumber([_fill(s) for s in m['steps']]),
        '验收标准': _dedup([_fill(s) for s in m['acceptance']]),
        '限制条件': _dedup([_fill(s) for s in m['rules']]),
        '输出规范': _dedup([_fill(s) for s in m['output_spec']]),
        '下游执行顺序': _dedup([_fill(s) for s in m['downstream']]),
    }
    if m['工具']:                                       # 增量字段（老宿主不读也不受影响）
        pkg['适用工具（行业标准）'] = [_tool_line(x) for x in m['工具']]
    if m['合规']:
        pkg['合规提示（行业标准）'] = list(m['合规'])
    if m.get('自测手段（行业标准）'):
        pkg['自测手段（行业标准）'] = list(m['自测手段（行业标准）'])
    if m.get('预案'):
        pkg['应变预案（行业标准）'] = list(m['预案'])
    pkg['前置经验（同行业）'] = _exp_lines((cls or {}).get('industry') or '', (cls or {}).get('scene') or '')
    return pkg


def to_human(pkg):
    """把任务包翻译回大白话（文档 34 行：执行完要转成普通人看得懂的话）"""
    l = []
    l.append('【我理解的】%s' % pkg['目标'])
    l.append('【归类】%s / %s / %s（把握度 %s）' % (pkg['匹配']['行业'], pkg['匹配']['场景'],
                                          pkg['匹配']['任务'], pkg['匹配']['置信度']))
    if pkg['匹配'].get('行业包') or pkg['匹配'].get('子域'):
        l.append('【套用的行业标准】%s%s' % (pkg['匹配'].get('行业包') or '（通用）',
                                     ('·' + pkg['匹配']['子域']) if pkg['匹配'].get('子域') else ''))
    l.append('【会分几步做】')
    for s in pkg['分步任务']:
        l.append('   ' + s)
    l.append('【不会越界的地方】%s' % '；'.join(pkg['限制条件']))
    l.append('【做完怎么算合格】%s' % '；'.join(pkg['验收标准']))
    if pkg.get('适用工具（行业标准）'):
        l.append('【要用到的工具】%s' % '；'.join(pkg['适用工具（行业标准）']))
    if pkg.get('合规提示（行业标准）'):
        l.append('【行业合规提醒】%s' % '；'.join(pkg['合规提示（行业标准）']))
    if pkg.get('自测手段（行业标准）'):
        l.append('【做完拿什么证明】%s' % '；'.join(pkg['自测手段（行业标准）']))
    if pkg.get('应变预案（行业标准）'):
        l.append('【卡住怎么办】%s' % '；'.join(pkg['应变预案（行业标准）']))
    if pkg.get('前置经验（同行业）'):
        l.append('【上次同类任务】%s' % '；'.join(pkg['前置经验（同行业）']))
    l.append('【最后交给】%s' % ' → '.join(pkg['下游执行顺序']))
    return '\n'.join(l)


# ── Phase3 增量自学习（文档 49/68 行）────────────────────────
# 规则：**只在"没匹配到模板"的自由模式下**才提炼候选；候选先进待审队列（pending_templates.json），
#       必须通过质量闸门 + 人工 approve 才并入 templates.json。绝不自动写库（防垃圾模板污染字典）。
PENDING_FILE = os.path.join(HERE, 'pending_templates.json')
_QUALITY = {'min_steps': 4, 'min_match': 4, 'min_required': 3, 'max_required': 5}


def _kw_from(text, filled):
    """给候选模板凑 match 关键词：从用户原话里取 2~4 字的中文片段 + 已填槽位值。"""
    ks = []
    for v in list((filled or {}).values()):
        if isinstance(v, str) and 2 <= len(v) <= 8:
            ks.append(v)
    for w in re.findall(r'[\u4e00-\u9fff]{2,6}', text or ''):
        ks.append(w)
    out = []
    for k in ks:
        if k not in out:
            out.append(k)
    return out[:10]


def draft_template(text, tpl, filled, cls):
    """把一次"自由模式"的完成结果提炼成候选模板（不写库，只返回草案 dict）"""
    keys = [k for k in (filled or {}).keys() if k != '卖点内容']
    for k in ('主题', '目标受众', '风格', '投放平台', '字数', '时长秒'):
        if len(keys) >= _QUALITY['min_required']:
            break
        if k not in keys:
            keys.append(k)
    steps = list((tpl or {}).get('steps') or ['① 澄清需求与产出物', '② 拆解可执行子任务',
                                              '③ 逐项产出并自检', '④ 交付并按反馈迭代'])
    mark = '①②③④⑤⑥'
    steps = [(s if str(s)[:1] in mark else '%s %s' % (mark[i] if i < len(mark) else '·', s))
             for i, s in enumerate(steps[:6])]
    goal = (tpl or {}).get('goal') or ('完成「{%s}」的%s' % (keys[0], cls.get('task') or '任务'))
    if not re.search(r'\{[^}]+\}', str(goal)):
        goal = '完成「{%s}」的%s' % (keys[0], cls.get('task') or '任务')
    ind = cls.get('industry') or '通用'
    tpls = load_templates()
    pack_name = ''
    if ind not in ('通用', None, ''):
        _p, pack_name = _pack_of(tpls, ind)
    if not pack_name:                       # 自由模式：按行业包关键词猜（v1.1 期3）
        for nm, p in (tpls.get(PACK_KEY) or {}).items():
            kws = list(p.get('match') or [])
            for sd in (p.get('_子域') or {}).values():
                kws += list(sd.get('match') or [])
            if any(k and k in (text or '') for k in kws):
                pack_name = nm
                break
    return {
        'id': 'auto_%s' % (abs(hash((text or '')[:40])) % 100000),
        'industry': cls.get('industry') or '通用',
        'scene': cls.get('scene') or '自由模式',
        'task': cls.get('task') or '临时任务流',
        'match': _kw_from(text, filled),
        'required': keys[:_QUALITY['max_required']],
        'optional': list((tpl or {}).get('optional') or ['交付物', '投放平台']),
        'rules': list((tpl or {}).get('rules') or ['不得虚构事实', '不得做夸大承诺']),
        'acceptance': list((tpl or {}).get('acceptance') or ['产出物完整可用', '符合用户描述的场景']),
        'output_spec': list((tpl or {}).get('output_spec') or ['结构化文本']),
        'downstream': list((tpl or {}).get('downstream') or ['内容生成 Agent', '校对 Agent']),
        'goal': goal,
        'steps': steps,
        'optional_defaults': dict((tpl or {}).get('optional_defaults') or {}),
        '来源': {'type': 'auto-draft', 'created_at': time.strftime('%F %T'),
                 'from_text': (text or '')[:80], 'hits': 1},
        '建议行业': ind,
        '建议行业包': pack_name or '（待建新行业包）',
    }


def _norm_txt(s):
    """归一化文本：去空白/编号/标点，用于判断"是不是照抄了模具"（v1.1 质检加严）"""
    return re.sub(r'[\s\u3000①-⑳0-9.、,，)）（(:：;；]', '', str(s or ''))


def _mold_norm():
    m = load_mold()
    return set(_norm_txt(x) for k in ('steps_base', 'steps_tail', 'rules_base', 'acceptance_base')
               for x in (m.get(k) or []))


def quality_check(d):
    """候选模板质量闸门：不合格不许入库（返回 (ok, 原因)）"""
    if len(d.get('steps') or []) < _QUALITY['min_steps']:
        return False, 'steps 少于 %d' % _QUALITY['min_steps']
    dup = [s for s in (d.get('steps') or []) if _norm_txt(s) in _mold_norm()]
    if dup:
        return False, '步骤与综合模具重复（行业/场景只该写差异）：%s' % str(dup[0])[:24]
    if len(d.get('match') or []) < _QUALITY['min_match']:
        return False, 'match 关键词少于 %d' % _QUALITY['min_match']
    n = len(d.get('required') or [])
    if not (_QUALITY['min_required'] <= n <= _QUALITY['max_required']):
        return False, 'required 数量 %d 不在 %d-%d' % (n, _QUALITY['min_required'], _QUALITY['max_required'])
    if not re.search(r'\{[^}]+\}', str(d.get('goal') or '')):
        return False, 'goal 没有 {占位符}'
    return True, 'ok'


def _load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save_draft(d, path=None):
    """候选入待审队列；同一 id 已存在则 hits+1（体现"这个需求反复出现"）"""
    path = path or PENDING_FILE
    data = _load_json(path, {'pending': [], 'rejected': []})
    for p in data['pending']:
        if p.get('id') == d.get('id'):
            p.setdefault('来源', {}).setdefault('hits', 1)
            p['来源']['hits'] = int(p['来源'].get('hits', 1)) + 1
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return 'exists', path
    data['pending'].append(d)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return 'added', path


def list_pending(path=None):
    return _load_json(path or PENDING_FILE, {'pending': [], 'rejected': []})


def approve_draft(did, templates_path=TPL_FILE, pending_path=None, 行业包=None):
    """人工审核通过 → 并入正式模板库（同 id 不重复；三级目录自动补 scene）
    v1.1 期3：可用 行业包="<包名>" 把候选里的约束/验收/步骤并入对应行业标准包（去重），
    避免长尾需求堆成一堆半成品模板。"""
    pending_path = pending_path or PENDING_FILE
    data = _load_json(pending_path, {'pending': [], 'rejected': []})
    hit = next((p for p in data['pending'] if p.get('id') == did), None)
    if not hit:
        return False, '待审队列里没有 %s' % did
    ok, why = quality_check(hit)
    if not ok:
        return False, '质量闸门不通过：%s' % why
    tpls = load_templates(templates_path)
    if any(t.get('id') == hit['id'] for t in tpls['templates']):
        return False, '该模板已入库'
    tpls['templates'].append(hit)
    cats = tpls.setdefault('三级目录', {})
    cats.setdefault(hit['industry'], [])
    if hit['scene'] not in cats[hit['industry']]:
        cats[hit['industry']].append(hit['scene'])
    merged = ''
    if 行业包:
        packs = tpls.setdefault(PACK_KEY, {})
        p = packs.setdefault(行业包, {
            '版本': 'pack/1.0', 'match': list(hit.get('match') or []), 'tools': [],
            'detail_rules': [], 'acceptance_extra': [],
            'steps_extra': {'前置': [], '中段': [], '后置': []},
            'slots_extra': [], 'compliance': [], 'downstream_extra': []})
        n0 = sum(len(p.get(k) or []) for k in ('detail_rules', 'acceptance_extra', 'downstream_extra'))
        p['detail_rules'] = _dedup(list(p.get('detail_rules') or []) + list(hit.get('rules') or []))
        p['acceptance_extra'] = _dedup(list(p.get('acceptance_extra') or []) + list(hit.get('acceptance') or []))
        p['downstream_extra'] = _dedup(list(p.get('downstream_extra') or []) + list(hit.get('downstream') or []))
        ex = p.setdefault('steps_extra', {'前置': [], '中段': [], '后置': []})
        ex['中段'] = _dedup(list(ex.get('中段') or []) + list(hit.get('steps') or []))
        n1 = sum(len(p.get(k) or []) for k in ('detail_rules', 'acceptance_extra', 'downstream_extra'))
        merged = '；已并入行业标准包「%s」（新增 %d 条约束/验收/下游）' % (行业包, max(0, n1 - n0))
    with open(templates_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(tpls, f, ensure_ascii=False, indent=2)
    data['pending'] = [p for p in data['pending'] if p.get('id') != did]
    with open(pending_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True, '已入库：%s/%s（模板总数 %d）%s' % (hit['industry'], hit['scene'],
                                                 len(tpls['templates']), merged)


def reject_draft(did, reason='', pending_path=None):
    pending_path = pending_path or PENDING_FILE
    data = _load_json(pending_path, {'pending': [], 'rejected': []})
    hit = next((p for p in data['pending'] if p.get('id') == did), None)
    if not hit:
        return False, '待审队列里没有 %s' % did
    hit['来源'] = dict(hit.get('来源') or {}, reject_reason=reason)
    data['rejected'].append(hit)
    data['pending'] = [p for p in data['pending'] if p.get('id') != did]
    with open(pending_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return True, '已驳回'


# ── 对外唯一入口：宿主 Agent 调这个 ────────────────────────
class Session:
    """一次任务会话（宿主可直接持有；无状态也可用 run_once）"""

    def __init__(self, templates=None):
        self.templates = templates or load_templates()
        self.text = ''
        self.filled = {}
        self.cls = None
        self.rounds = 0
        self.max_rounds = 6

    def start(self, utterance):
        self.text = utterance
        self.cls = classify(utterance, self.templates)
        tpl = self.cls.get('template')
        self.filled.update(extract_slots(utterance, tpl))
        return self._step()

    def answer(self, reply):
        q = getattr(self, '_last_q', None)
        if q:
            slot = q['slot']
            v = str(reply).strip()
            if '秒' in v or '分' in v:
                n = _num_cn(v) or (int(re.sub(r'\D', '', v) or 0) or None)
                if n:
                    v = n
            elif slot in ('卖点数量', '字数', '页面数量'):
                d = re.sub(r'\D', '', v)
                if d:
                    v = int(d)
            self.filled[slot] = v
        self.text += ' ｜ ' + str(reply)
        _rstr = str(reply)
        self.filled.update({k: v for k, v in extract_slots(_rstr, self.cls.get('template')).items()
                            if k not in self.filled})
        self.rounds += 1
        return self._step()

    def _step(self):
        tpl = self.cls.get('template')
        mold = load_mold(self.templates)
        free_mode = not tpl
        missing = missing_slots(tpl, self.filled, mold, free_mode)
        if missing and self.rounds < self.max_rounds:
            q = next_question(tpl, missing, mold)
            self._last_q = q
            return {'state': 'ask', 'round': self.rounds, 'question': q['question'],
                    'slot': q['slot'], 'filled': self.filled, 'missing': missing}
        self._last_q = None
        pkg = build_package(self.text, tpl, self.filled, self.cls, self.templates)
        remember(pkg)                                   # 经验登记（失败不影响出包）
        _nc = (self.cls or {}).get('新行业候选')        # 期A：新行业登记候选池
        _txt = self.text or ''
        if _nc is None and (self.cls or {}).get('industry') == '通用' and len(_txt) >= 6 \
                and any(k in _txt for k in ('店', '公司', '行业', '生意', '客户', '产品', '服务', '业务')):
            try:
                from fanrenge import pack_draft as _PD        # 懒加载：用更聪明的行业名提取（期B）
                _nm, _bg = _PD.extract_industry_name(_txt)
                if _nm:
                    register_candidate(_txt, _nm, _bg, re.findall(r'[\u4e00-\u9fff]{2,4}', _txt)[:6])
            except Exception:
                pass
        elif _nc:
            try:
                register_candidate(_txt, _nc['行业'], _nc.get('大类') or '', _nc.get('命中') or [])
            except Exception:
                pass
        if _nc:
            pkg['新行业候选'] = '%s（大类：%s，命中词：%s）——已在候选池登记，达到阈值自动出行业包草案' \
                % (_nc['行业'], _nc.get('大类') or '未分类', '/'.join(_nc.get('命中') or []))
        try:                                            # 期D：把本次任务的新约束/验收/坑登记为升级建议（不自动入库）
            from fanrenge import pack_draft as _PD
            _PD.upgrade_candidates_from_task(pkg)
        except Exception:
            pass
        out = {'state': 'done', 'round': self.rounds, 'package': pkg, 'human': to_human(pkg),
               'filled': self.filled, 'missing': missing}
        # ── Phase3 增量自学习（文档 49/68 行）──────────────────────────────
        # **只在没匹配到模板（自由模式/通用降级）时**才提炼候选，进待审队列等人工审核；
        # 命中模板的正常任务不动字典（否则会污染模板库）。
        if not tpl and self.cls.get('industry') in ('通用', None, ''):
            try:
                d = draft_template(self.text, tpl, self.filled, self.cls)
                save_draft(d)
                out['候选模板'] = {'id': d['id'], '状态': 'pending（待人工审核）',
                                   '提示': '这是一次自由模式任务，已提炼为候选模板；人工审核通过后进入模板库'}
            except Exception as e:          # 自学习失败绝不影响主流程
                out['候选模板'] = {'状态': 'draft_failed', '原因': str(e)[:80]}
        return out


def run_once(utterance, answers=None, templates=None):
    """无状态便捷入口：answers 为按顺序的追问回答列表"""
    s = Session(templates)
    r = s.start(utterance)
    for a in (answers or []):
        if r['state'] != 'ask':
            break
        r = s.answer(a)
    return r
