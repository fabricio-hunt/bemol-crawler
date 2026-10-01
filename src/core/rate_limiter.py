"""Adaptive rate limiter for smooth request distribution"""
import random
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Lowest rate the limiter will back off to when the server keeps throttling
MIN_REQUESTS_PER_SECOND = 0.2

# Consecutive successful responses needed before the rate is raised again
RECOVERY_STREAK = 20

# Fraction of the configured rate added back on each recovery step
RECOVERY_STEP_RATIO = 0.1

# Backoff used when a throttling response carries no usable Retry-After
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0

# Upper bound for a server-provided Retry-After, so a hostile or broken
# header cannot stall the crawl indefinitely
MAX_RETRY_AFTER_SECONDS = 300.0


def parse_retry_after(value):
    """
    Parse an HTTP Retry-After header.

    Accepts either delta-seconds ("120") or an HTTP-date. Returns the wait in
    seconds clamped to [0, MAX_RETRY_AFTER_SECONDS], or None when the header
    is missing or unparseable.
    """
    if not value:
        return None
    value = value.strip()

    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at is None:
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()

    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


class RateLimiter:
    """
    Rate limiter that spaces requests evenly and adapts to server throttling.

    Requests are spread over time at the configured rate. When the server
    signals throttling (429/503), penalize() pauses every caller until the
    server's Retry-After has elapsed and halves the rate (multiplicative
    decrease). A long streak of successful responses gradually restores the
    rate (additive increase), never above the configured value.
    """

    def __init__(self, requests_per_second=1.0):
        """
        Initialize rate limiter.

        Args:
            requests_per_second: Target request rate (e.g., 1.0 = 1 req/sec, 0.5 = 1 req every 2 sec)
        """
        self.lock = threading.Lock()
        self.configured_rate = max(0.01, requests_per_second)
        self.requests_per_second = self.configured_rate
        self.min_interval = 1.0 / self.requests_per_second
        self.next_slot_time = 0.0
        self.blocked_until = 0.0
        self.success_streak = 0
        self.consecutive_penalties = 0

    def acquire(self):
        """
        Acquire permission to make a request.
        Blocks until this caller's slot arrives and no throttling pause is active.
        """
        while True:
            with self.lock:
                now = time.time()
                slot = max(now, self.next_slot_time, self.blocked_until)
                self.next_slot_time = slot + self.min_interval

            wait = slot - now
            if wait > 0:
                time.sleep(wait)

            # A penalty may have been registered while this caller slept
            with self.lock:
                if time.time() >= self.blocked_until:
                    return

    def penalize(self, retry_after=None):
        """
        Register a throttling response from the server.

        Pauses all callers for retry_after seconds (or an exponential backoff
        with jitter when the server gave none) and halves the request rate.
        Returns the pause applied, in seconds.
        """
        with self.lock:
            if retry_after is None:
                backoff = BACKOFF_BASE_SECONDS * (2 ** self.consecutive_penalties)
                retry_after = min(BACKOFF_MAX_SECONDS, backoff) * random.uniform(0.5, 1.5)

            self.consecutive_penalties += 1
            self.success_streak = 0
            self.blocked_until = max(self.blocked_until, time.time() + retry_after)
            self._set_current_rate(max(MIN_REQUESTS_PER_SECOND, self.requests_per_second / 2))
            return retry_after

    def reward(self):
        """Register a successful response; slowly restores the rate after throttling."""
        with self.lock:
            self.consecutive_penalties = 0
            if self.requests_per_second >= self.configured_rate:
                return

            self.success_streak += 1
            if self.success_streak >= RECOVERY_STREAK:
                self.success_streak = 0
                step = self.configured_rate * RECOVERY_STEP_RATIO
                self._set_current_rate(min(self.configured_rate, self.requests_per_second + step))

    def update_rate(self, requests_per_second):
        """Update the configured rate limit dynamically"""
        with self.lock:
            self.configured_rate = max(0.01, requests_per_second)
            self.success_streak = 0
            self._set_current_rate(self.configured_rate)

    def get_state(self):
        """Snapshot of the limiter for status reporting"""
        with self.lock:
            return {
                'effective_rate': round(self.requests_per_second, 2),
                'configured_rate': round(self.configured_rate, 2),
                'is_throttled': (self.requests_per_second < self.configured_rate
                                 or time.time() < self.blocked_until),
            }

    def _set_current_rate(self, requests_per_second):
        """Apply a new effective rate. Caller must hold the lock."""
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / self.requests_per_second
