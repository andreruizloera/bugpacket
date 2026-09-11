"""Entry point for the two CPython exception-chain fixtures.

    python3 chained.py cause     # `raise X from Y`
    python3 chained.py context   # raised while handling another exception
    python3 chained.py both      # a cause chain, handled, failing again

All three exit non-zero with a real chained traceback. `record-traces.sh`
captures each into `traces/`, so the fixtures are output CPython actually
printed rather than text written from memory of what it prints.

Three runs because each shape needs its own uncaught exception, and three
SHAPES because the separator lines CPython puts between the tracebacks look
alike and mean opposite things. See `shop/pricing.py`.
"""

import sys

from shop import pricing


def main() -> None:
    shape = sys.argv[1] if len(sys.argv) > 1 else "cause"
    if shape == "cause":
        pricing.convert_cents(2499, "GBP")
    elif shape == "context":
        pricing.report_total("GBP")
    elif shape == "both":
        pricing.checkout(2499, "GBP")
    else:
        raise SystemExit(f"unknown shape: {shape}")


main()
