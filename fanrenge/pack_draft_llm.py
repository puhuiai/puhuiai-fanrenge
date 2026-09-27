# -*- coding: utf-8 -*-
"""普惠AI 期C：用免费大模型（Agnes）润色/补全行业包草案的差异内容

原则
  · 只是「润色差异内容」，不改变结构；输出仍要过 pack_draft.quality_gate
  · 没有 key / 网络不通 / 返回不合规 → 直接抛异常，调用方回落规则版（绝不阻断主链路）
  · 只发必要的行业信息，不发用户隐私

配置：key 读 C:\\Users\\Administrator\\.agnes\\api_key.txt（或环境变量 AGNES_API_KEY）
      base https://api.agnes-ai.cn/v1   model agnes-2.5-flash
"""
import io
import json
import os
import re
import urllib.request

KEY_FILE = r'C:\Users\Administrator\.agnes\api_key.txt'
BASE = os.environ.get('AGNES_BASE', 'https://api.agnes-ai.cn/v1')
MODEL = os.environ.get('AGNES_MODEL', 'agnes-2.5-flash')

PROMPT = """你在为一个「任务指令引擎」写行业包（只写该行业与通用标准的差异）。
行业：{industry}　　大类：{big}
用户真实需求样例：
{samples}

请输出严格 JSON（不要markdown、不要解释），字段如下，全部用中文、每条不超过 40 字、具体可执行：
{{
 "tools": ["该行业用什么工具完成任务（必须含一条『…没有时：…』的替代路径）"],
 "detail_rules": ["该行业的 2~4 条硬性做法"],
 "compliance": ["该行业的 1~3 条合规红线"],
 "自测手段": ["交付前怎么自证做对了（可执行动作）"],
 "预案": ["最可能卡住的 1~2 种情况及备选路径"]
}}"""


def _key():
    k = os.environ.get('AGNES_API_KEY')
    if k:
        return k.strip()
    try:
        return io.open(KEY_FILE, encoding='utf-8').read().strip()
    except Exception:
        return ''


def _post(path, payload, timeout=90):
    req = urllib.request.Request(BASE.rstrip('/') + path,
                                 data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + _key()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def _extract_json(txt):
    """从模型输出里抠出 JSON（容忍 ```json 包裹与前后废话）"""
    txt = (txt or '').strip()
    m = re.search(r'\{[\s\S]*\}', txt)
    if not m:
        raise ValueError('模型没有返回 JSON')
    return json.loads(m.group(0))


def enrich(pack, industry, big='', samples=None):
    """用大模型补/替换差异内容；失败抛异常由调用方回落"""
    if not _key():
        raise RuntimeError('没有可用的大模型 key（未配置 Agnes）')
    msgs = [{'role': 'system', 'content': '你是严谨的行业任务标准撰写助手，只输出 JSON。'},
            {'role': 'user', 'content': PROMPT.format(
                industry=industry, big=big or '未分类',
                samples='\n'.join('- %s' % s for s in (samples or [])[:5]) or '（无）')}]
    resp = _post('/chat/completions', {'model': MODEL, 'messages': msgs, 'temperature': 0.3,
                                       'max_tokens': 1200})
    txt = (((resp.get('choices') or [{}])[0].get('message') or {}).get('content')) or ''
    data = _extract_json(txt)

    def take(key, cur):
        v = data.get(key)
        if isinstance(v, list):
            v = [str(x).strip() for x in v if str(x).strip()]
            if v:
                return v[:4]
        return cur

    def to_tool(x):
        """把模型给的工具条目规范成 dict（名/用途/没有时）——项目约定：必须写替代路径"""
        if isinstance(x, dict):
            t = dict(x)
        else:
            t = {'用途': str(x)}
            m = re.match(r'^\s*([^：:（(]{2,16})[：:]\s*(.+)$', str(x))
            t['名'] = (m.group(1).strip() if m else str(x)[:12])
            t['用途'] = (m.group(2).strip() if m else str(x))
        if not my_noalt(t):
            t['没有时'] = '用现有资料/替代工具人工补做一遍，并在交付里写明这个限制'
        return t

    def my_noalt(t):
        return bool(t.get('没有时')) or ('没有时' in (t.get('用途') or '')) or ('替代' in (t.get('用途') or ''))

    tools = data.get('tools')
    if isinstance(tools, list) and tools:
        pack['tools'] = [to_tool(x) for x in tools[:3]]
    pack['detail_rules'] = take('detail_rules', pack.get('detail_rules'))
    pack['compliance'] = take('compliance', pack.get('compliance'))
    pack['自测手段'] = take('自测手段', pack.get('自测手段'))
    pack['预案'] = take('预案', pack.get('预案'))
    pack['llm'] = {'模型': MODEL, '时间': __import__('time').strftime('%F %T')}
    return pack


if __name__ == '__main__':
    p = enrich({'tools': [], 'detail_rules': [], 'compliance': [], '自测手段': [], '预案': []},
               '露营地运营', '生活服务', ['给露营地做亲子活动引流方案'])
    print(json.dumps(p, ensure_ascii=False, indent=1))
