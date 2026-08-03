"""Shared parsing for the JSON protocol agents respond with."""

from __future__ import annotations

import json
import re


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
            return {"action": action, "content": content}

    raise json.JSONDecodeError("No valid JSON found", raw, 0)
