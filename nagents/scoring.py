"""Answer extraction and exact-match scoring."""
import re

_ANSWER_LINE = re.compile(r"answer\s*[:=]\s*\$?(-?[\d,]+)", re.IGNORECASE)
_ANY_INT = re.compile(r"-?\d+")


def extract_answer(text: str) -> str:
    """Pull the final integer answer out of a model reply, canonicalized.

    Prefers the last 'Answer: <number>' line; falls back to the last integer
    anywhere in the text. Returns "" when nothing parses.
    """
    matches = _ANSWER_LINE.findall(text or "")
    if matches:
        raw = matches[-1]
    else:
        nums = _ANY_INT.findall(text or "")
        if not nums:
            return ""
        raw = nums[-1]
    raw = raw.replace(",", "")
    try:
        return str(int(raw))
    except ValueError:
        return ""


def is_correct(reply_text: str, truth: str) -> bool:
    return extract_answer(reply_text) == str(int(truth))
