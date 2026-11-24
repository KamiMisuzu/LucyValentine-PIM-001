# -*- coding: utf-8 -*-
"""Type-safe tool registry — adapted from baremetal-react/tools.py (MIT)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        args_schema: type[BaseModel],
        func: Callable[..., Any],
    ):
        self.name = name
        self.description = description
        self.args_schema = args_schema
        self.func = func

    def call(self, args_dict: dict) -> str:
        try:
            validated = self.args_schema(**(args_dict or {}))
            result = self.func(**validated.model_dump())
            return str(result)
        except ValidationError as e:
            parts = [f"Validation Error for tool '{self.name}':"]
            for err in e.errors():
                loc = ".".join(str(x) for x in err["loc"])
                parts.append(f" - {loc}: {err['msg']}")
            return "\n".join(parts)
        except Exception as e:  # noqa: BLE001 — feed back to agent
            return f"Execution Error: {e}"

    def schema(self) -> dict:
        return self.args_schema.model_json_schema()


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def get_system_prompt_segment(self) -> str:
        lines = ["Available Tools:"]
        for t in self._tools.values():
            lines.append(f"- {t.name}: {t.description}")
            lines.append(f"  Schema: {t.schema()}")
        return "\n".join(lines)
