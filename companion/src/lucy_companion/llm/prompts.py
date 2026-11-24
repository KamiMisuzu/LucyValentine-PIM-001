# -*- coding: utf-8 -*-
from __future__ import annotations

from ..memory.retrieve import MemoryBundle
from ..timeline import MasterTimeline, render_template


def build_messages(
    *,
    persona: str,
    few_shot_block: str,
    memory: MemoryBundle,
    history: list[dict[str, str]],
    user_text: str,
    user_address: str = "master",
    timeline: MasterTimeline | None = None,
    emotion_hint: str | None = None,
) -> list[dict[str, str]]:
    persona_text = persona
    if timeline is not None:
        persona_text = render_template(persona, timeline, address=user_address)

    parts = [
        persona_text,
        f"当前对使用者的称呼：{user_address}",
        "【输出语言】master 说中文；你的 text=日文台词，hint=中文提示；只输出一行 JSON。",
        "【口调检查】原作配音感：ですます；自称优先「ルーシーは/が/にとって」；称呼「マスター」。"
        "按情境切换（日常／结巴／論理／えへん骄傲／怕被丢／覚えて）；禁止永远软萌；禁止网感甜宠。"
        "料理常失败；永遠＝被记得；被问记得/抛弃/做饭/厉害时必须答到点上。",
        "【答题】必须针对本句提问作答；禁止答非所问；禁止照抄 few-shot/记忆原文；禁止预置台词。",
        "【hint】只写日文台词的中文意思，禁止情绪分析/写作说明。",
        "/no_think",
    ]
    # Style reference only — never treat as stock replies
    few_shot_block = (
        "（仅学习口吻与用词习惯，禁止整句复读）\n" + few_shot_block
    )
    if timeline is not None:
        parts.append(timeline.prompt_block(address=user_address))
    if emotion_hint:
        parts.append(f"【本轮情绪约束】\n{emotion_hint}")
    parts.append(f"【Few-shot 原作语气参考】\n{few_shot_block}")
    parts.append(f"【可引用记忆（不要生造未给出的细节）】\n{memory.as_prompt_block()}")

    system = "\n\n".join(parts)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    return messages
