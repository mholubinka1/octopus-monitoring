NULL_STRINGS = ["null"]


def is_none_or_whitespace(
    s: str | None,
) -> bool:
    if not s:
        return True
    if s.isspace():
        return True
    return s.strip() in NULL_STRINGS
