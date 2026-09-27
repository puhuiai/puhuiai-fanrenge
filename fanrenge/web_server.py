# -*- coding: utf-8 -*-
"""普惠AI指令拆解引擎 · 网页版（零安装、离线可用）

用途：浏览器打开就能用——大白话进，标准化任务包出。适合演示、获客、给不懂装软件的客户用。
技术：只用 Python 标准库（http.server），不联网、不调大模型、零第三方依赖。

用法：
  python fanrenge/web_server.py                 # 默认 127.0.0.1:8899，数据取仓库内置
  python fanrenge/web_server.py --port 8900 --data D:\\puhui_data   # 指定端口与数据目录（外置数据=行业包可升级）
  python fanrenge/web_server.py --no-open       # 不自动开浏览器（测试用）
"""
import argparse
import io
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from fanrenge import engine as E            # noqa: E402

try:
    from fanrenge import pack_draft as D    # noqa: E402
except Exception:
    D = None

SESSIONS = {}
APPS_TTL = 6 * 3600

# 允许挂在子路径下（公网部署用：nginx 把 /app/ 反代到本服务）
# 用法：--prefix /app  或在页面里用 __PREFIX__ 占位（默认空=根路径，本地双击/直连不变）
PREFIX = os.environ.get('PUHUI_PREFIX') or ''


def configure(data_dir=None):
    """数据目录（模板库/词典/经验台账/候选池）可外置 —— 桌面版据此实现「行业包可升级」"""
    if not data_dir:
        return HERE
    os.makedirs(data_dir, exist_ok=True)
    for fn in ('templates.json', 'industries.json', 'pending_templates.json', 'experience.json'):
        src, dst = os.path.join(HERE, fn), os.path.join(data_dir, fn)
        if not os.path.exists(dst) and os.path.exists(src):
            with io.open(src, encoding='utf-8') as f:
                io.open(dst, 'w', encoding='utf-8', newline='\n').write(f.read())
    E.TPL_FILE = os.path.join(data_dir, 'templates.json')
    E.INDUSTRY_FILE = os.path.join(data_dir, 'industries.json')
    E.PENDING_FILE = os.path.join(data_dir, 'pending_templates.json')
    E.EXP_FILE = os.path.join(data_dir, 'experience.json')
    if D:
        D.TPL = E.TPL_FILE
        D.PENDING = E.PENDING_FILE
    return data_dir


def ask(text, answers=None, sid=None):
    """一问一答：无 sid 走无状态；有 sid 走多轮会话"""
    answers = list(answers or [])
    tpls = E.load_templates()
    if not answers:
        r = E.run_once(text, templates=tpls) if text else {'state': 'ask'}
        if sid and r.get('state') != 'done':
            s = E.Session(tpls)
            s.start(text)
            SESSIONS[sid] = s
        return _pack(r, sid)
    if sid and sid in SESSIONS:
        s = SESSIONS[sid]
        r = s.answer(answers[0])
        for a in answers[1:]:
            if r.get('state') == 'done':
                break
            r = s.answer(a)
        if r.get('state') == 'done':
            SESSIONS.pop(sid, None)
        return _pack(r, sid)
    r = E.run_once(text, answers=answers, templates=tpls)
    return _pack(r, sid)


def _pack(r, sid=None):
    if r.get('state') == 'done':
        pkg = r.get('package') or {}
        return {'state': 'done', 'human': r.get('human') or E.to_human(pkg), 'package': pkg, 'sid': sid}
    return {'state': 'ask', 'question': r.get('question'), 'round': r.get('round'), 'sid': sid}


PAGE = u"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>普惠AI指令拆解引擎</title>
<style>
:root{--bg:#0f1218;--card:#171c26;--line:#26303f;--fg:#e8edf5;--dim:#9aa8bd;--acc:#4ea1ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.7 -apple-system,"Microsoft YaHei",sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:22px 16px 60px}
h1{font-size:21px;margin:0 0 4px}.sub{color:var(--dim);font-size:13px;margin-bottom:18px}
textarea{width:100%;min-height:96px;background:var(--card);color:var(--fg);border:1px solid var(--line);
 border-radius:12px;padding:12px;font:15px/1.6 inherit;resize:vertical}
button{background:var(--acc);color:#04121f;border:0;border-radius:10px;padding:10px 22px;font-weight:700;
 margin-top:10px;cursor:pointer;font-size:15px}
button:disabled{opacity:.5}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-top:14px}
.card h3{margin:0 0 8px;font-size:15px;color:var(--acc)}
pre{white-space:pre-wrap;word-break:break-word;margin:0;font:14px/1.7 inherit}
.small{color:var(--dim);font-size:12.5px}
.q{background:#1d2635;border-left:3px solid var(--acc);padding:10px 12px;border-radius:8px;margin-top:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 18px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1>普惠AI指令拆解引擎</h1>
<div class="sub">你说大白话，它出派工单 —— 全自动标准化拆解任务指令（零算力、离线可跑）</div>
<textarea id="t" placeholder="例如：做一个旅游线路咨询登记单页，客户填姓名电话意向线路，双击离线可开"></textarea>
<div><button id="go">生成任务包</button>
<span class="small" id="st" style="margin-left:12px"></span></div>
<div id="out"></div>
</div>
<script>
let sid='w'+Date.now().toString(36)+Math.random().toString(36).slice(2,8);  /* 🔴 会话号必须由前端生成：服务端只在"带着 sid"时才建会话，靠响应里回传会一直是 null，多轮追问就永远答不完 */
const $=s=>document.querySelector(s);
function esc(s){return (s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function send(text,answer){
  const r=await fetch('__PREFIX__/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text:text,answer:answer,sid:sid})});
  return await r.json();
}
async function run(text){
  $('#st').textContent='处理中…';
  let d=await send(text);
  while(d.state==='ask'){
    const a=prompt(d.question||'还需要补充信息：');
    if(a===null){$('#st').textContent='已取消';return;}
    d=await send(text,a);
  }
  sid=d.sid||sid;render(d);
}
function render(d){
  $('#st').textContent='已生成';
  const p=d.package||{}, rows=[];
  const add=(k,v)=>{if(v&&String(v).length)rows.push('<div><b>'+esc(k)+'</b>：'+esc(v)+'</div>')};
  add('行业',(p['匹配']||{})['行业']);add('场景',(p['匹配']||{})['场景']);
  add('行业包',(p['匹配']||{})['行业包']);add('目标',p['目标']);
  const list=(k,arr)=>arr&&arr.length?'<div class="card"><h3>'+esc(k)+'</h3><pre>'+esc(arr.join('\\n'))+'</pre></div>':'';
  let html='<div class="card"><h3>大白话版（直接照做）</h3><pre>'+esc(d.human)+'</pre></div>';
  html+=list('分步任务',p['分步任务'])+list('必须守的规矩',p['必须守的规矩'])+list('验收标准',p['验收标准']);
  html+=list('适用工具（行业标准）',p['适用工具（行业标准）'])+list('行业合规提醒',p['合规提示（行业标准）']);
  html+=list('做完拿什么证明',p['自测手段（行业标准）'])+list('卡住怎么办',p['应变预案（行业标准）']);
  html+=list('上次同类任务',p['前置经验（同行业）']);
  if(p['新行业候选'])html+='<div class="card"><h3>新行业候选</h3><pre>'+esc(p['新行业候选'])+'</pre></div>';
  html+='<div class="card"><h3>结构化任务包（给智能体用）</h3><pre>'+esc(JSON.stringify(p,null,1))+'</pre></div>';
  $('#out').innerHTML=html;
  window.scrollTo(0,document.body.scrollHeight);
}
$('#go').onclick=()=>{const t=$('#t').value.trim();if(t)run(t);};
$('#t').addEventListener('keydown',e=>{if(e.key==='Enter'&&e.ctrlKey)$('#go').click();});
fetch('__PREFIX__/api/health').then(r=>r.json()).then(h=>{$('#st').textContent='引擎 v'+h.version+' ｜ 行业包 '+h.packs+' 个 ｜ 模板 '+h.templates+' 个';});
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200, ctype='application/json; charset=utf-8'):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):
        pass

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ('/', '/index.html'):
            return self._send(PAGE.replace('__PREFIX__', PREFIX).encode('utf-8'),
                              ctype='text/html; charset=utf-8')
        if p == '/api/health':
            t = E.load_templates()
            return self._send({'ok': True, 'version': (io.open(os.path.join(ROOT, 'VERSION'), encoding='utf-8')
                                                       .read().strip() if os.path.exists(os.path.join(ROOT, 'VERSION')) else '1.2.0'),
                               'packs': len(t.get('_行业包') or {}), 'templates': len(t.get('templates') or []),
                               'industries': len(E.known_industries()) if hasattr(E, 'known_industries') else 0})
        return self._send({'ok': False, 'error': 'not found'}, 404)

    def do_POST(self):
        if urlparse(self.path).path != '/api/ask':
            return self._send({'ok': False, 'error': 'not found'}, 404)
        n = int(self.headers.get('Content-Length') or 0)
        try:
            data = json.loads(self.rfile.read(n).decode('utf-8') or '{}')
        except Exception:
            return self._send({'ok': False, 'error': 'bad json'}, 400)
        text = (data.get('text') or '').strip()
        ans = data.get('answer')
        answers = [ans] if isinstance(ans, str) and ans else []
        try:
            r = ask(text, answers, data.get('sid'))
            return self._send(r)
        except Exception as e:
            return self._send({'state': 'error', 'error': str(e)[:300]}, 500)


def serve(port=8899, data_dir=None, open_browser=True, host='127.0.0.1'):
    configure(data_dir)
    for i in range(20):                                  # 端口被占就顺延
        try:
            httpd = ThreadingHTTPServer((host, port + i), H)
            port = port + i
            break
        except OSError:
            continue
    else:
        raise SystemExit('端口 %s 起不来' % port)
    shown = '127.0.0.1' if host in ('0.0.0.0', '') else host   # 0.0.0.0 只是监听地址，给人看的还是本机
    url = 'http://%s:%d/' % (shown, port)
    print('普惠AI指令拆解引擎 网页版已启动：%s（监听 %s）' % (url, host))
    print('数据目录：%s' % (data_dir or HERE))
    print('（Ctrl+C 退出）')
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(url)), daemon=True).start()
    httpd.serve_forever()


def main(argv=None):
    global PREFIX
    ap = argparse.ArgumentParser(description='普惠AI指令拆解引擎 · 网页版')
    ap.add_argument('--port', type=int, default=8899)
    ap.add_argument('--data', default=os.environ.get('PUHUI_DATA') or None)
    ap.add_argument('--prefix', default=os.environ.get('PUHUI_PREFIX') or '',
                    help='挂在子路径时填，如 /app（nginx 反代场景）')
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--host', default=os.environ.get('PUHUI_HOST') or '127.0.0.1',
                    help='监听地址；容器里必须填 0.0.0.0，否则端口映射进不来')
    ap.add_argument('--selftest', action='store_true', help='跑一次出包并打印，然后退出')
    a = ap.parse_args(argv)
    PREFIX = (a.prefix or '').rstrip('/')
    if a.selftest:
        configure(a.data)
        r = ask('做一个旅游线路咨询登记单页：客户填姓名电话意向线路；双击离线可开')
        if r.get('state') != 'done':
            r = ask('做一个旅游线路咨询登记单页：客户填姓名电话意向线路；双击离线可开',
                    ['1 个落地页', '云南六日游咨询登记', '填表存本机', '旅游客户'])
        print('[selftest] state=%s 行业=%s' % (r.get('state'), (r.get('package') or {}).get('匹配', {}).get('行业')))
        print((r.get('human') or '')[:400])
        return 0
    serve(a.port, a.data, not a.no_open, a.host)
    return 0


if __name__ == '__main__':
    sys.exit(main())
