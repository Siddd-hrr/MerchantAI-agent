from __future__ import annotations

from typing import Any

STUB_PROMO_TEXT = (
    "Promo tip: Try our smart substitute picks above for similar quality and better availability today."
)

_THOUGHT_BLOCK_TYPES = frozenset({"thinking", "reasoning"})


def _is_thought_part(part: Any) -> bool:
    if isinstance(part, dict):
        if str(part.get("type", "")).lower() in _THOUGHT_BLOCK_TYPES:
            return True
        if part.get("thought") is True:
            return True
        return False
    if getattr(part, "thought", False):
        return True
    part_type = getattr(part, "type", None)
    return bool(part_type and str(part_type).lower() in _THOUGHT_BLOCK_TYPES)


def _text_from_part(part: Any) -> str:
    if _is_thought_part(part):
        return ""
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        text = part.get("text")
        if text is not None:
            return str(text)
        thinking = part.get("thinking")
        if thinking is not None and str(part.get("type", "")).lower() not in _THOUGHT_BLOCK_TYPES:
            return str(thinking)
        return ""
    text = getattr(part, "text", None)
    if text is not None:
        return str(text)
    return ""


def _coerce_response_text(raw: Any) -> str:
    if hasattr(raw, "content"):
        raw = raw.content
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts = [_text_from_part(part) for part in raw]
        return "".join(part for part in parts if part).strip()
    return str(raw).strip() if raw is not None else ""


async def generate_creative_promo(
    llm: Any,
    *,
    unavailable_item_name: str,
    alternatives: list[dict[str, Any]],
) -> str:
    alternatives_preview = ", ".join(
        f"{item.get('brand', '').strip()} {item.get('name', '').strip()}".strip()
        for item in alternatives[:3]
    ) or "No alternatives listed"
    prompt = (
        "Write one short promotional line in plain English for a merchant replacing an out-of-stock item. "
        "Do not use emojis. Keep under 20 words.\n"
        f"Out-of-stock item: {unavailable_item_name}\n"
        f"Suggested alternatives: {alternatives_preview}"
    )
    try:
        response = await llm.ainvoke(
            prompt,
            thinking_budget=0,
            include_thoughts=False,
        )
        text = _coerce_response_text(response)
        return text or STUB_PROMO_TEXT
    except TypeError:
        # Older/fake LLM clients may not accept thinking kwargs.
        try:
            response = await llm.ainvoke(prompt)
            text = _coerce_response_text(response)
            return text or STUB_PROMO_TEXT
        except Exception:
            return STUB_PROMO_TEXT
    except Exception:
        return STUB_PROMO_TEXT
