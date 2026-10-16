"""Logging for the webhook service (Q-12).

httpx logs every request URL at INFO, and Telegram URLs hold the bot token, so the httpx and
httpcore loggers are held at WARNING. As a second guard, a filter on the root handlers replaces
any known secret that still reaches a log line.
"""

import logging
from collections.abc import Iterable

QUIET_LOGGERS = ("httpx", "httpcore")
REDACTED = "[redacted]"


class RedactSecrets(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if any(s in message for s in self._secrets):
            for secret in self._secrets:
                message = message.replace(secret, REDACTED)
            record.msg, record.args = message, None
        return True


def configure_logging(secrets: Iterable[str] = ()) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    redact = RedactSecrets(secrets)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redact)
