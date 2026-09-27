# 普惠AI指令拆解引擎（EveryAgent / fanrenge）

**大白话进，任务包出。**

把生活语言的需求自动追问补齐参数，拆解成结构化、可执行的任务包，过 7 道门禁校验后入库或分派。
纯 Python 标准库实现：**零算力、不调大模型、不联网、离线可跑**。

- 官网：https://puhuiai.com.cn
- 网页版（免安装）：https://puhuiai.com.cn/app/
- 产品页：https://puhuiai.com.cn/fanrenge
- 当前版本：v1.3.1（13 个任务模板 / 17 个行业包 / 35 个行业词典）

## 四种用法，按需选

| 形态 | 怎么用 | 要不要装东西 |
|---|---|---|
| 网页版 | 打开 https://puhuiai.com.cn/app/ | 不用装 |
| 技能包（插件版） | 下载 zip 解压，配 AI 助手/智能体用 | 不用装 |
| 桌面版 | 下载绿色包解压双击 exe | 免安装，但首次运行 Windows 可能提示未签名 |
| pip / Docker | 见下 | 要 Python 或 Docker |

## 安装

```bash
pip install puhuiai-fanrenge
```

## 命令行用

```bash
fanrenge                       # 交互式
fanrenge "做一个旅游线路咨询登记单页"
fanrenge --selftest            # 自检
fanrenge review                # 复核待审草案
```

## 起网页版（本地/内网）

```bash
python -m fanrenge.web_server --port 8899
# 容器里必须加 --host 0.0.0.0，否则端口映射进不来
python -m fanrenge.web_server --port 8899 --host 0.0.0.0 --no-open
```

## 核心设计

1. **只出草案，绝不自动写库** —— AI/规则产出一律进待审队列，人审通过才入库。
2. **零依赖** —— 只用 Python 标准库，不调大模型、不占 Token、离线可用。
3. **可验收** —— 每个任务包自带分步任务 + 验收标准 + 合规/预案字段。
4. **自学习** —— 用户每次真实需求都会沉淀成候选，人审后并入行业包。

## 目录

```
fanrenge/            引擎包（engine.py 规则引擎、cli.py 命令行、web_server.py 网页版）
fanrenge/templates.json     13 个任务模板
fanrenge/industries.json    17 个行业包
fanrenge/pending_templates.json  待审候选（人审入口）
docs_用户手册.md     面向用户的手册
```

## 许可

许可证待定（暂保留所有权利）。商用/二次分发请先联系作者。

## 联系

汪君 · 普惠AI · https://puhuiai.com.cn
