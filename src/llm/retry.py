"""Tenacity-based retry helper that injects previous error feedback into the next attempt."""
from __future__ import annotations

import logging
from typing import Any, Callable

from tenacity import Retrying, stop_after_attempt, wait_exponential

logger = logging.getLogger("src.llm.retry")

CallFn = Callable[[str, dict[str, Any]], Any]


def retry_with_feedback(
    call_fn: CallFn,
    prompt_name: str,
    variables: dict[str, Any],
    max_attempts: int = 3,
) -> Any:
    """Run call_fn(prompt_name, variables) with tenacity exponential backoff.

    On each failure the previous exception message is injected into a working copy of
    variables under the "__feedback__" key, so the next attempt's prompt can include it.
    Returns the successful result or re-raises the last exception after exhausting attempts.
    """
    working: dict[str, Any] = dict(variables)

    retrying = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )

    try:
        for attempt in retrying:
            with attempt:
                try:
                    return call_fn(prompt_name, working)
                except Exception as exc:
                    logger.warning(
                        "retry_with_feedback: %s failed (attempt %s/%s): %s",
                        prompt_name,
                        attempt.retry_state.attempt_number,
                        max_attempts,
                        exc,
                    )
                    working["__feedback__"] = str(exc)
                    raise
    except Exception:
        logger.error(
            "retry_with_feedback: exhausted %d attempts for %s",
            max_attempts,
            prompt_name,
        )
        raise