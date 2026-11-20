import threading
import time
from collections import deque

class UserLimitExceededError(Exception):
    pass

class MultiUserManager:
    def __init__(
        self,
        max_history=50,
        max_requests_per_minute=30,
        max_tokens_per_minute=4000,
    ):
        self.max_history = max_history
        self.max_requests_per_minute = (
            max_requests_per_minute
        )
        self.max_tokens_per_minute = (
            max_tokens_per_minute
        )
        self._lock = threading.RLock()
        self._histories = {}
        self._requests = {}
        self._tokens = {}

    def _ensure_user(self, user_id):
        if not user_id:
            raise ValueError(
                "user_id is required"
            )
        if user_id not in self._histories:
            self._histories[user_id] = []
            self._requests[user_id] = deque()
            self._tokens[user_id] = deque()

    def _prune(self, user_id, now):
        reqs = self._requests[user_id]
        while reqs and now - reqs[0] >= 60:
            reqs.popleft()
        toks = self._tokens[user_id]
        while toks and now - toks[0][0] >= 60:
            toks.popleft()

    def add_message(
        self, user_id, role, content
    ):
        with self._lock:
            self._ensure_user(user_id)
            h = self._histories[user_id]
            h.append(
                {"role": role, "content": content}
            )
            if len(h) > self.max_history:
                del h[: len(h) - self.max_history]
            return list(h)

    def get_history(self, user_id):
        with self._lock:
            self._ensure_user(user_id)
            return list(
                self._histories[user_id]
            )

    def clear_user(self, user_id):
        with self._lock:
            self._ensure_user(user_id)
            self._histories[user_id] = []
            self._requests[user_id] = deque()
            self._tokens[user_id] = deque()

    def check_request_allowed(
        self, user_id, tokens=0
    ):
        now = time.time()
        with self._lock:
            self._ensure_user(user_id)
            self._prune(user_id, now)
            if len(self._requests[user_id]) >= (
                self.max_requests_per_minute
            ):
                raise UserLimitExceededError(
                    "request limit exceeded"
                )
            used = sum(
                t for _, t in self._tokens[user_id]
            )
            if used + tokens > (
                self.max_tokens_per_minute
            ):
                raise UserLimitExceededError(
                    "token limit exceeded"
                )
            return True

    def record_request(
        self, user_id, tokens=0
    ):
        now = time.time()
        with self._lock:
            self.check_request_allowed(
                user_id, tokens=tokens
            )
            self._requests[user_id].append(now)
            if tokens:
                self._tokens[user_id].append(
                    (now, tokens)
                )

    def get_usage(self, user_id):
        now = time.time()
        with self._lock:
            self._ensure_user(user_id)
            self._prune(user_id, now)
            used = sum(
                t for _, t in self._tokens[user_id]
            )
            return {
                "user_id": user_id,
                "requests_last_minute": len(
                    self._requests[user_id]
                ),
                "tokens_last_minute": used,
                "history_len": len(
                    self._histories[user_id]
                ),
            }
