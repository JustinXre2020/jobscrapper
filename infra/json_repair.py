"""Repair malformed JSON from LLM responses.

Common issue: models like Liquid AI produce invalid escape sequences
such as \\- \\. \\: inside JSON strings. This module strips them
before parsing.
"""

import re


# Valid JSON escape sequences: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
# Everything else (e.g. \-, \., \:, \') is invalid.
_INVALID_ESCAPE_RE = re.compile(
    r'\\(?!["\\/bfnrtu])'
)


def repair_json(text: str) -> str:
    """Fix common JSON issues from LLM output.

    1. Extract the JSON object/array from markdown fences or surrounding text.
    2. Remove invalid escape sequences (e.g. \\- -> -).

    Args:
        text: Raw LLM response that may contain JSON.

    Returns:
        Cleaned JSON string ready for json.loads().
    """
    # Strip markdown code fences
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove opening fence (with optional language tag)
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        # Remove closing fence
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()

    # Extract the outermost JSON object or array
    start = -1
    for i, ch in enumerate(stripped):
        if ch in "{[":
            start = i
            break
    if start == -1:
        return stripped  # No JSON found, return as-is

    # Find matching closing bracket
    open_char = stripped[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape_next = False
    end = len(stripped)

    for i in range(start, len(stripped)):
        ch = stripped[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    json_str = stripped[start:end]

    # Fix invalid escape sequences inside strings
    json_str = _INVALID_ESCAPE_RE.sub(_replace_invalid_escape, json_str)

    return json_str


def _replace_invalid_escape(match: re.Match) -> str:
    """Remove the backslash from an invalid escape, keeping the character."""
    # match.group(0) is e.g. "\\-", we return just "-"
    return match.group(0)[1:]
