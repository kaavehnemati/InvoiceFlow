import json
import logging
import sys

from app.core.config import settings

# Context arrives as extra={"context": {...}} rather than as flat keyword
# arguments. A flat extra= would silently collide with LogRecord's own
# attributes -- message, args, name, module and friends are all taken.


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Machine-parseable, which is what a log aggregator wants: CloudWatch can
    filter on event="invoice_rejected" without anyone writing a regex.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            **getattr(record, "context", {}),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """Readable at a glance, for a terminal.

    INFO     invoice_created  invoice_id=1 invoice_number=INV-001
    """

    def format(self, record: logging.LogRecord) -> str:
        line = f"{record.levelname:<8} {record.getMessage()}"
        context = getattr(record, "context", {})
        if context:
            line += "  " + " ".join(f"{k}={v}" for k, v in context.items())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging() -> None:
    """Send application logs to stdout in the format this environment wants.

    stdout rather than a file: a container should write to its output stream
    and let the platform decide where that goes. Phase 29's Fargate tasks and
    Phase 44's CloudWatch both assume exactly that.

    The format is chosen by APP_ENV -- readable while developing, JSON where
    something is going to parse it.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        HumanFormatter() if settings.app_env == "development" else JsonFormatter()
    )

    root = logging.getLogger()
    # Replace rather than append, so repeated calls cannot duplicate every line.
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)
