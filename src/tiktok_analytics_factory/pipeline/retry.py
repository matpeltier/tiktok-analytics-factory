"""Bounded, configured retry policy for transient provider/network errors."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "rate limit",
    "503",
    "429",
    "temporary",
)


class TransientError(Exception):
    """Raised by stages to signal a retryable transient failure."""


@dataclass(frozen=True)
class RetryPolicy:
    """Explicit bounded retry. No indefinite silent retries."""

    max_attempts: int = 3
    backoff_seconds: float = 1.0
    retryable_exceptions: tuple[type[BaseException], ...] = (TransientError,)

    def to_dict(self) -> dict:
        return {
            "max_attempts": self.max_attempts,
            "backoff_seconds": self.backoff_seconds,
            "retryable": [e.__name__ for e in self.retryable_exceptions],
        }


@dataclass
class RetryOutcome:
    value: object | None
    attempts: int
    succeeded: bool
    errors: list[str] = field(default_factory=list)


def run_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryOutcome:
    """Execute ``fn`` with the bounded policy; last error is re-raised if final."""
    errors: list[str] = []
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return RetryOutcome(fn(), attempts=attempt, succeeded=True)
        except policy.retryable_exceptions as exc:
            errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
            logger.warning("transient failure (%s)", errors[-1])
            if attempt < policy.max_attempts:
                sleep(policy.backoff_seconds * attempt)
    return RetryOutcome(None, attempts=policy.max_attempts, succeeded=False, errors=errors)
