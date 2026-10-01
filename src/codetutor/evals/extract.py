"""Get the Python code out of a model's reply.

Models wrap code in Markdown fences, explain it, show a draft first, or add an "example usage"
block after the solution. The rules, in order:

1. Drop reasoning inside <think>...</think> (a <think> that is never closed runs to the end).
2. Find every ``` block. Pick the last block that defines the function (`def name(` at the start
   of a line). If none does, pick the last ```python block, then the last block of any kind.
3. No block at all: use the whole reply (some models answer with plain code, no fences).

The method is returned with the code, so the report can count "the model did not follow the
format" separately from "the model wrote wrong code".

Known limitation: a line starting with ``` inside the code itself (e.g. in a string) ends the
block early.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

PYTHON_TAGS = frozenset({"python", "python3", "py"})

# A <think> section, closed or not. Reasoning models (e.g. Qwen3, DeepSeek-R1) write one first.
_THINK = re.compile(r"<think>.*?(?:</think>|\Z)", re.DOTALL)
# A fenced block: an opening ``` line with an optional language tag, the code, and a closing ```
# line. A block that is never closed (the reply was cut off) runs to the end of the reply.
_FENCE = re.compile(
    r"^[ \t]*```[ \t]*(?P<tag>[\w+-]*)[^\n]*\n(?P<code>.*?)(?:^[ \t]*```[ \t]*$|\Z)",
    re.DOTALL | re.MULTILINE,
)


class ExtractMethod(StrEnum):
    """How the code was found in the reply."""

    PYTHON_BLOCK = "python_block"  # a ```python (or ```py) block
    OTHER_BLOCK = "other_block"  # a ``` block with no language tag, or another tag
    RAW = "raw"  # no block: the whole reply is used as code
    EMPTY = "empty"  # nothing left: an empty reply, reasoning only, or an empty block


class Extraction(BaseModel):
    """The code to grade, and how it was found."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    method: ExtractMethod


@dataclass(frozen=True)
class _Block:
    tag: str
    code: str

    @property
    def is_python(self) -> bool:
        return self.tag.lower() in PYTHON_TAGS


def _clean(code: str) -> str:
    """Remove common indentation (blocks inside Markdown lists are indented) and blank edges."""
    return textwrap.dedent(code).strip("\n")


def _pick_block(blocks: list[_Block], function_name: str) -> _Block:
    """The last block that defines the function; else the last python block; else the last."""
    defines = re.compile(rf"^def\s+{re.escape(function_name)}\s*\(", re.MULTILINE)
    with_function = [block for block in blocks if defines.search(block.code)]
    python_blocks = [block for block in blocks if block.is_python]
    for candidates in (with_function, python_blocks, blocks):
        if candidates:
            return candidates[-1]
    raise ValueError("no blocks to pick from")  # unreachable: callers pass at least one block


def extract_code(reply: str, function_name: str) -> Extraction:
    """Return the code to grade from a model's `reply` (see the module docstring for the rules)."""
    text = reply.replace("\r\n", "\n").replace("\r", "\n")
    text = _THINK.sub("", text)
    blocks = [
        _Block(tag=match["tag"], code=_clean(match["code"])) for match in _FENCE.finditer(text)
    ]
    if blocks:
        block = _pick_block(blocks, function_name)
        method = ExtractMethod.PYTHON_BLOCK if block.is_python else ExtractMethod.OTHER_BLOCK
        code = block.code
    else:
        method = ExtractMethod.RAW
        code = _clean(text)
    if not code.strip():
        return Extraction(code="", method=ExtractMethod.EMPTY)
    return Extraction(code=code + "\n", method=method)
