"""Code golf character rule. The team UI shows the same rule and uses the same logic."""

GOLF_RULE_TEXT = (
    "Characters = Unicode code points after turning Windows line endings (\\r\\n) into \\n "
    "and removing whitespace at the very end of the file."
)


TRAILING_WS = " \t\n\r\f\v"  # ASCII only, so the browser counter (lib/golf.ts) matches exactly


def golf_chars(code: str) -> int:
    return len(code.replace("\r\n", "\n").rstrip(TRAILING_WS))
