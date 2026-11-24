# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"G:\LIngyuanli\Project\Lucy\companion\src")))

from lucy_companion.agent.runner import LucyAgent
from lucy_companion.config import load_settings
from lucy_companion.llm.style_filter import parse_lucy_json
from lucy_companion.timeline import build_timeline

s = load_settings()
tl = s.raw.get("timeline", {})
agent = LucyAgent(
    s,
    timeline=build_timeline(
        birthday_str=str(tl.get("master_birthday", "2006-08-14")),
        restored_on=str(tl.get("restored_on") or "") or None,
    ),
)
identity = agent.identity_text()
payload = {
    "emotion": "happy",
    "text": "ルーシーはマスターにとって大切な存在です。",
    "hint": "x",
}
messages = [
    {
        "role": "system",
        "content": (
            identity
            + "\n/no_think\n"
            "把下面草稿改成更贴题的 Lucy 日文台词。"
            "失败原因：proud-question needs objective pride then insecurity。"
            "厉害→客観的に世界最高の製品＋不安。"
            "text 只能是一句日文。hint=短中文。"
            '只输出 JSON：{"emotion":"...","text":"...","hint":"..."}'
        ),
    },
    {
        "role": "user",
        "content": f"master问：你觉得自己厉害吗\n草稿：{json.dumps(payload, ensure_ascii=False)}",
    },
]
raw = agent.llm.chat(messages)
print("RAW", repr(raw[:1200]))
print("PARSED", parse_lucy_json(raw))
