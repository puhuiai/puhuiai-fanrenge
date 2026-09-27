# -*- coding: utf-8 -*-
"""普惠AI（Fanrenge）· 口语需求 → 标准化 AI 任务工作流

对外接口（宿主智能体只用这三个）：
    from fanrenge import run_once, Session, load_templates
    r = run_once("帮我做一条90秒的房产短视频")     # 无状态：返回 ask/done
    s = Session(); s.start(...); s.answer("高端稳重风")   # 有状态：多轮追问

形态：可嵌入**规则技能包**（不是大模型、不占算力）。宿主 Agent 提供"说话"能力，普惠AI提供流程与校验。
"""
from .engine import (  # noqa: F401
    Session,
    build_package,
    classify,
    extract_slots,
    load_templates,
    missing_slots,
    next_question,
    run_once,
    to_human,
)

def _read_version():
    try:
        import io as _io
        import os as _os
        return _io.open(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                     'VERSION'), encoding='utf-8').read().strip() or '1.2.0'
    except Exception:
        return '1.2.0'


__version__ = _read_version()
__all__ = ['Session', 'run_once', 'load_templates', 'classify', 'extract_slots',
           'missing_slots', 'next_question', 'build_package', 'to_human', '__version__']
