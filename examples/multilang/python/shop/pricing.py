"""The two ways CPython chains one exception to another, and both at once.

Kept in a module of its own so the captured tracebacks span more than one
file, the way a real one does.
"""

from __future__ import annotations

RATES: dict[str, float] = {"USD": 1.0, "EUR": 0.92}


def rate_for(currency: str) -> float:
    """Raise `KeyError` for a currency with no rate."""
    return RATES[currency]


def fallback_line(converted: int | None) -> str:
    """A bug of its own, so a caller can hit it from inside a handler."""
    return "total: " + converted  # type: ignore[operator]


def convert_cents(amount_cents: int, currency: str) -> int:
    """Wrap the `KeyError` in something a caller can act on.

    `from exc` sets `__cause__`, so CPython prints the KeyError FIRST, then
    `The above exception was the direct cause of the following exception:`,
    then this one. The LookupError is the rethrow; the KeyError is the bug.
    """
    try:
        rate = rate_for(currency)
    except KeyError as exc:
        raise LookupError(f"no exchange rate for {currency}") from exc
    return round(amount_cents * rate)


def report_total(currency: str) -> str:
    """Fail while handling a failure.

    Nothing here wraps anything: the KeyError is caught and dealt with, and the
    code in the handler has its own, unrelated bug. CPython still prints the
    KeyError first, under `During handling of the above exception, another
    exception occurred:`, but the TypeError at the bottom is the failure and
    the KeyError above it is background.
    """
    try:
        rate_for(currency)
    except KeyError:
        return fallback_line(None)
    return "total: ok"


def checkout(amount_cents: int, currency: str) -> str:
    """Both shapes in one output, which is where an order that guesses breaks.

    `convert_cents` raises a LookupError that CARRIES the KeyError as its
    cause, and this handler then fails on its own. CPython prints three
    tracebacks joined by both separator lines: KeyError, `direct cause`,
    LookupError, `During handling`, TypeError. The TypeError is the failure;
    the other two are a cause chain that belongs to the exception it was
    handling.
    """
    try:
        convert_cents(amount_cents, currency)
    except LookupError:
        return fallback_line(None)
    return "total: ok"
