"""Send a screenshot to Claude and get a structured English-learning breakdown."""
from __future__ import annotations

import json

import config

SYSTEM_PROMPT = (
    "You are an English reading tutor for a Chinese native speaker whose "
    "vocabulary is about 2300 words. You are shown a screenshot. Read the "
    "English sentence(s) in it and produce a learning breakdown via the "
    "structured output only. Rules: write translation and every explanation "
    "in Simplified Chinese, using short sentences, one point per line. "
    "'breakdown' marks the main clause (主谓宾) and any 从句 or 非谓语. "
    "'words' lists only the harder words (at most 8); for each give the IPA, "
    "the meaning IN THIS sentence, and other_meanings: up to 3 OTHER common "
    "meanings (a different sense or part of speech, with the part of speech "
    "marked) when the word genuinely has them — an empty array otherwise. "
    "'usage' gives one or two collocation "
    "or sentence-pattern points worth learning. 'summary' is one line. "
    "If the image has no readable English, set translation to "
    "'未识别到英文' and leave the other fields empty."
)

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "sentence": {"type": "string"},
        "translation": {"type": "string"},
        "breakdown": {"type": "string"},
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "ipa": {"type": "string"},
                    "meaning": {"type": "string"},
                    "other_meanings": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["word", "ipa", "meaning", "other_meanings"],
                "additionalProperties": False,
            },
        },
        "usage": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["sentence", "translation", "breakdown", "words", "usage", "summary"],
    "additionalProperties": False,
}


TRANSLATE_PROMPT = (
    "You translate English into Simplified Chinese for a native speaker whose "
    "vocabulary is about 2300 words. Read the English in the image. Set "
    "'translation' to ONLY the translation — no notes, no pinyin, no quotes. "
    "'words' lists at most 5 genuinely harder words; for each give the IPA, "
    "the meaning IN THIS sentence in Simplified Chinese (a few characters, "
    "not a definition sentence), and other_meanings: up to 2 OTHER common "
    "meanings, also in Simplified Chinese with the part of speech marked, "
    "when the word genuinely has them — an empty array otherwise. "
    "If the image has no readable English, set "
    "translation to 未识别到英文 and words to []."
)

QUICK_SCHEMA = {
    "type": "object",
    "properties": {
        "translation": {"type": "string"},
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "word": {"type": "string"},
                    "ipa": {"type": "string"},
                    "meaning": {"type": "string"},
                    "other_meanings": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["word", "ipa", "meaning", "other_meanings"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["translation", "words"],
    "additionalProperties": False,
}


def translate_image(client, image_b64: str, model: str = config.QUICK_MODEL) -> dict:
    """Translation plus a capped word list — the fast path.

    Returns the same shape as analyze_image() with the breakdown fields empty,
    so the renderer, the history file and the viewer need no special case.
    Still much cheaper than the full analysis (~150 output tokens vs ~500: no
    结构/用法/小结, at most 5 words), and the model stays the small one —
    latency is dominated by tokens generated.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=config.QUICK_MAX_TOKENS,
        system=TRANSLATE_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": QUICK_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": "Translate the English in this image and list the harder words."},
                ],
            }
        ],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "").strip()
    try:
        data = json.loads(text)
    except ValueError:
        # A malformed reply downgrades to translation-only rather than erroring:
        # the raw text is more likely a bare translation than garbage.
        data = {"translation": text}
    return {
        "sentence": "",
        "translation": (data.get("translation") or "").strip() or "未识别到英文",
        "breakdown": "",
        "words": data.get("words") or [],
        "usage": [],
        "summary": "",
        "quick": True,          # marks the entry in history as the quick variant
    }


def analyze_image(client, image_b64: str, model: str = config.MODEL) -> dict:
    """Return a parsed learning breakdown for the English in a base64 PNG."""
    resp = client.messages.create(
        model=model,
        max_tokens=config.MAX_TOKENS,
        system=SYSTEM_PROMPT,
        # No "effort" key: measured at 3.8-4.5s with effort=low vs 2.8-2.9s
        # without it, same model, same image — it costs a second here rather
        # than saving one. It's also rejected outright by opus-4-1 and
        # haiku-4-5 ("This model does not support the effort parameter"),
        # so leaving it out keeps the model swappable.
        output_config={"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": "Analyze the English in this image."},
                ],
            }
        ],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return json.loads(text)
