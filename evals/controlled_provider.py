"""Bọc provider bằng gate và ghi chẩn đoán đã che key."""
import json
import re
import time
import urllib.error


def error_details(exc, secret=""):
    def clean(value):
        text = str(value)
        if secret:
            text = text.replace(secret, "[REDACTED]")
        return re.sub(
            r"sk-[A-Za-z0-9_.*-]+", "[REDACTED]", text
        )[:600]

    details = {
        "exception": type(exc).__name__,
        "message": clean(exc),
    }
    cause = exc
    while cause is not None:
        if isinstance(cause, urllib.error.HTTPError):
            details["http_status"] = cause.code
            headers = cause.headers or {}
            names = (
                "Retry-After",
                "x-ratelimit-limit-requests",
                "x-ratelimit-remaining-requests",
                "x-ratelimit-reset-requests",
                "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-tokens",
                "x-ratelimit-reset-tokens",
                "x-request-id",
            )
            details["headers"] = {
                name: clean(headers.get(name))
                for name in names
                if headers.get(name) is not None
            }
            try:
                body = json.loads(cause.read(65_536))
                error = body.get("error", {})
                if isinstance(error, dict):
                    for key in ("code", "type", "message"):
                        if error.get(key) is not None:
                            details[key] = clean(error[key])
            except (ValueError, TypeError, AttributeError, OSError):
                pass
            break
        cause = cause.__cause__
    return details


class ControlledProvider:
    def __init__(
        self, base, gate, events, case_id, stage,
        on_update=None, output_limit=2048,
    ):
        self.base = base
        self.gate = gate
        self.events = events
        self.case_id = case_id
        self.stage = stage
        self.on_update = on_update
        self.output_limit = output_limit

    def notify(self):
        if self.on_update is not None:
            self.on_update()

    def complete(self, messages, schemas):
        # Ước lượng bảo thủ bằng byte UTF-8, không phải tokenizer.
        content = json.dumps(
            {"messages": messages, "tools": schemas},
            ensure_ascii=False,
        )
        estimated = (
            len(content.encode("utf-8"))
            + self.output_limit + 1024
        )
        attempt = self.gate.acquire(estimated)
        event = {
            "case_id": self.case_id,
            "stage": self.stage,
            "attempt": attempt,
            "started_at_unix": time.time(),
            "estimated_tokens": estimated,
            "status": "started",
        }
        self.events.append(event)
        self.notify()

        try:
            reply = self.base.complete(messages, schemas)
        except Exception as exc:
            details = error_details(
                exc, getattr(self.base, "key", "")
            )
            event.update(status="error", error=details)
            self.gate.stop_reason = (
                "Provider thất bại; dừng phiên để kiểm tra."
            )
            self.notify()
            raise RuntimeError(
                json.dumps(details, ensure_ascii=False)
            ) from exc

        event.update(
            status="completed",
            usage=reply.get("usage", {}),
        )
        self.notify()
        return reply