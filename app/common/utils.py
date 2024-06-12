from typing import Optional

NULL_STRINGS = ["null"]


def is_none_or_whitespace(
    s: Optional[str],
) -> bool:
    if not s:
        return True
    if s.isspace():
        return True
    return s.strip() in NULL_STRINGS
