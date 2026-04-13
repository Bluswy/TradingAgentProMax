from __future__ import annotations

import json
import re
from typing import Any


def strip_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    return cleaned


def extract_balanced_json(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def apply_common_json_repairs(text: str) -> str:
    repaired = str(text or "")
    repaired = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    repaired = re.sub(r"^\s*json\s*", "", repaired, flags=re.IGNORECASE)
    return repaired.strip()


def parse_json_object(content: str, *, source: str = "LLM output") -> dict[str, Any]:
    cleaned = strip_code_fences(content)
    candidates: list[str] = [cleaned]
    balanced = extract_balanced_json(cleaned)
    if balanced and balanced not in candidates:
        candidates.append(balanced)

    errors: list[json.JSONDecodeError] = []
    for candidate in candidates:
        variants = [candidate]
        repaired = apply_common_json_repairs(candidate)
        if repaired != candidate:
            variants.append(repaired)
        for variant in variants:
            try:
                parsed = json.loads(variant)
            except json.JSONDecodeError as error:
                errors.append(error)
                continue
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError(f"{source} is not a JSON object", variant, 0)
            return parsed

    if errors:
        raise errors[-1]
    raise json.JSONDecodeError(f"{source} did not return valid JSON", cleaned, 0)
