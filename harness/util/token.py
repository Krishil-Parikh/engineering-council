"""Token estimation (opencode: core/src/util/token.ts)."""

CHARS_PER_TOKEN = 4


def estimate(text: str) -> int:
    # JS Math.round rounds halves up; Python's round() rounds them to even.
    return max(0, int(len(text) / CHARS_PER_TOKEN + 0.5))
