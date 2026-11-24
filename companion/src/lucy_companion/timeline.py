# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class MasterTimeline:
    birthday: date
    today: date
    age: int
    next_birthday: date
    days_to_next_birthday: int
    restored_year: int
    restored_age: int

    def prompt_block(self, address: str = "master") -> str:
        return (
            f"【当前时间线｜自动推进】\n"
            f"- 今天：{self.today.isoformat()}\n"
            f"- {address} 生日：{self.birthday.isoformat()}\n"
            f"- {address} 现在：{self.age} 岁\n"
            f"- 下一次生日：{self.next_birthday.isoformat()}（还有 {self.days_to_next_birthday} 天，到时会变成 {self.age + 1} 岁）\n"
            f"- Lucy 被当前 {address} 唤醒/修复的年份记为：{self.restored_year}（当时约 {self.restored_age} 岁）\n"
            f"- 禁止把 {address} 说成中年、三十岁左右、或“修了十五年才重逢”的那个时间线。\n"
            f"- 年龄要跟今天对齐；过了生日就自动长大。"
        )

    def as_dict(self) -> dict:
        return {
            "birthday": self.birthday.isoformat(),
            "today": self.today.isoformat(),
            "age": self.age,
            "next_birthday": self.next_birthday.isoformat(),
            "days_to_next_birthday": self.days_to_next_birthday,
            "restored_year": self.restored_year,
            "restored_age": self.restored_age,
        }


def parse_birthday(value: str) -> date:
    value = value.strip().replace("/", "-").replace(".", "-")
    # allow 2006-8-14 / 2006-08-14
    parts = value.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid birthday: {value}")
    y, m, d = (int(parts[0]), int(parts[1]), int(parts[2]))
    return date(y, m, d)


def calc_age(birthday: date, today: date) -> int:
    years = today.year - birthday.year
    if (today.month, today.day) < (birthday.month, birthday.day):
        years -= 1
    return years


def next_birthday_after(birthday: date, today: date) -> date:
    candidate = date(today.year, birthday.month, birthday.day)
    if candidate <= today:
        candidate = date(today.year + 1, birthday.month, birthday.day)
    return candidate


def build_timeline(
    birthday_str: str = "2006-08-14",
    today: date | None = None,
    restored_on: str | None = None,
) -> MasterTimeline:
    birthday = parse_birthday(birthday_str)
    today = today or date.today()
    age = calc_age(birthday, today)
    nxt = next_birthday_after(birthday, today)

    if restored_on:
        restored_date = parse_birthday(restored_on)
    else:
        # default: treat "now" as restoration moment for private continuity
        restored_date = today
    restored_age = calc_age(birthday, restored_date)

    return MasterTimeline(
        birthday=birthday,
        today=today,
        age=age,
        next_birthday=nxt,
        days_to_next_birthday=(nxt - today).days,
        restored_year=restored_date.year,
        restored_age=restored_age,
    )


def render_template(text: str, timeline: MasterTimeline, address: str = "master") -> str:
    return (
        text.replace("{{master_age}}", str(timeline.age))
        .replace("{{master_birthday}}", timeline.birthday.isoformat())
        .replace("{{today}}", timeline.today.isoformat())
        .replace("{{restored_year}}", str(timeline.restored_year))
        .replace("{{restored_age}}", str(timeline.restored_age))
        .replace("{{next_birthday}}", timeline.next_birthday.isoformat())
        .replace("{{address}}", address)
    )
