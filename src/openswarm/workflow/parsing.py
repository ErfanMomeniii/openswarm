"""Shared parsing for the JSON protocol agents respond with."""

from __future__ import annotations

import json
import re

#: Models trained on tool use often answer in this XML shape instead of JSON,
#: whatever the prompt asks for:
#:     <invoke name="write_file">
#:       <parameter name="path">a.txt</parameter>
#:     </invoke>
INVOKE_BLOCK = re.compile(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', re.DOTALL)
INVOKE_PARAM = re.compile(r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>', re.DOTALL)


def parse_tool_call_xml(text: str) -> dict | None:
    """Read an XML-style tool call into the same dict shape as the JSON protocol.

    Returns None when the text holds no such call, so callers can fall through
    to the JSON parsing they already do.
    """
    block = INVOKE_BLOCK.search(text)
    if not block:
        return None

    parsed = {"action": block.group(1).strip()}
    for name, value in INVOKE_PARAM.findall(block.group(2)):
        # Providers commonly pad parameter bodies with newlines.
        parsed[name.strip()] = value.strip("\n")
    return parsed


def _unescape(text: str) -> str:
    """Turn JSON escape sequences into real characters.

    The regex fallback slices the raw response, so `\\n` and `\\"` arrive
    literally. Without this a code block comes back as one unusable line.
    """
    try:
        return json.loads(f'"{text}"')
    except json.JSONDecodeError:
        return (
            text.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\")
        )


def parse_agent_response(raw: str) -> dict:
    """Parse JSON response from agent.

    Handles: bare JSON, markdown code fences, JSON embedded in prose,
    and broken JSON where content has unescaped characters.
    """
    text = raw.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines[1:] if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Extract first JSON object using balanced brace matching
    start = text.find("{")
    if start >= 0:
        brace_depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    # Try to extract action field — model may have broken JSON with valid action
    action_match = re.search(r'"action"\s*:\s*"(\w+)"', text)
    if action_match:
        action = action_match.group(1)
        # Extract content between "content": " and the last "
        content_match = re.search(r'"content"\s*:\s*"(.*)', text, re.DOTALL)
        if content_match:
            content = content_match.group(1)
            # Remove trailing "} or similar
            content = re.sub(r'"\s*\}\s*$', "", content)
            return {"action": action, "content": _unescape(content)}

    # Last: the model may have answered in tool-call XML rather than JSON.
    tool_call = parse_tool_call_xml(text)
    if tool_call is not None:
        return tool_call

    raise json.JSONDecodeError("No valid JSON found", raw, 0)
