import logging
import re
from typing import Final


SENSITIVE_FIELD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""(?ix)
    (
        ["']?
        (?:prompt|prompts|messages|input|inputs|
           output|outputs|response|responses|
           completion|completions|generated_text)
        ["']?
        \s*[:=]\s*
    )
    (
        ["'][^"']*["'] |
        \[[^\]]*\] |
        \{[^}]*\} |
        [^,\s]+
    )
    """
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()

        redacted_message = SENSITIVE_FIELD_PATTERN.sub(r"\1[REDACTED]", message,)

        record.msg = redacted_message
        record.args = ()

        return True