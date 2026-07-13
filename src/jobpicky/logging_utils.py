from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from .error_safety import redact_text


class SensitiveDataFilter(logging.Filter):
    """Redact credential-shaped values before any configured handler emits them."""

    def __init__(self, secrets: Iterable[str] = ()):
        super().__init__()
        self.secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if record.exc_info:
                exception = record.exc_info[1]
                safe_exception = redact_text(exception, secrets=self.secrets)
                record.msg = f"{redact_text(record.msg, secrets=self.secrets)}: {safe_exception}"
                record.args = ()
                record.exc_info = None
                record.exc_text = None
            record.msg = redact_text(record.msg, secrets=self.secrets)
            if isinstance(record.args, dict):
                record.args = {key: self._filter_arg(value) for key, value in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._filter_arg(value) for value in record.args)
            elif record.args:
                record.args = self._filter_arg(record.args)
        except BaseException:
            record.msg = "[REDACTED]"
            record.args = ()
        return True

    def _filter_arg(self, value):
        # Preserve numeric arguments so format strings such as ``%d`` retain
        # their normal logging semantics; redact string-like values centrally.
        if value is None or isinstance(value, (bool, int, float, complex)):
            return value
        return redact_text(value, secrets=self.secrets)


def setup_logging(log_path: str | Path, *, secrets: Iterable[str] = ()) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safety_filter = SensitiveDataFilter(secrets)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    stream_handler = logging.StreamHandler()
    file_handler.addFilter(safety_filter)
    stream_handler.addFilter(safety_filter)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[file_handler, stream_handler],
        force=True,
    )
