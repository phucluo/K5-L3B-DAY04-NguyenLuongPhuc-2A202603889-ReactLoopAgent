"""Giới hạn request; module này không tự gọi API."""
import time


class RequestStopped(RuntimeError):
    pass


class RequestGate:
    def __init__(
        self,
        max_requests,
        min_interval=7.0,
        token_budget=48_000,
        clock=time.monotonic,
        sleeper=time.sleep,
    ):
        if max_requests < 1 or min_interval < 7 or token_budget < 1:
            raise ValueError("Ngân sách hoặc khoảng cách không hợp lệ.")

        self.max_requests = max_requests
        self.min_interval = min_interval
        self.token_budget = token_budget
        self.used = 0
        self.stop_reason = None
        self.last_started = None
        self.recent = []
        self.clock = clock
        self.sleeper = sleeper

    def acquire(self, estimated_tokens):
        if self.stop_reason:
            raise RequestStopped(self.stop_reason)

        if self.used >= self.max_requests:
            self.stop_reason = "Đã đạt ngân sách request của phiên."
            raise RequestStopped(self.stop_reason)

        if not 0 < estimated_tokens <= self.token_budget:
            self.stop_reason = (
                "Ước lượng token của một request vượt ngân sách."
            )
            raise RequestStopped(self.stop_reason)

        while True:
            now = self.clock()
            self.recent = [
                (started, tokens)
                for started, tokens in self.recent
                if now - started < 60
            ]

            delay = 0.0
            if self.last_started is not None:
                delay = max(
                    0.0,
                    self.last_started + self.min_interval - now,
                )

            reserved = sum(tokens for _, tokens in self.recent)
            if reserved + estimated_tokens > self.token_budget:
                delay = max(
                    delay,
                    self.recent[0][0] + 60 - now,
                )

            if delay > 0:
                self.sleeper(delay)
                continue

            self.used += 1
            self.last_started = now
            self.recent.append((now, estimated_tokens))
            return self.used