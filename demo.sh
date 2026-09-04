#!/usr/bin/env bash
# Demo: introduce a realistic bug in the example shop app, run its tests
# through bugpacket, and show the packet that comes out.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  uv venv --python 3.13 >/dev/null
fi
uv sync --quiet

TARGET="examples/shopapp/shop/payment.py"
BACKUP="$(mktemp)"
cp "$TARGET" "$BACKUP"
restore() { cp "$BACKUP" "$TARGET"; rm -f "$BACKUP"; }
trap restore EXIT

# The bug: the coupon field gets read under the wrong name.
python3 - "$TARGET" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
p.write_text(p.read_text().replace('coupon["percent"]', 'coupon["percentage"]'))
PY

echo '$ cd examples/shopapp'
echo '$ bugpacket run -- python -m pytest tests/test_payment.py'
echo
(
  cd examples/shopapp
  uv run --project ../.. bugpacket run -- python -m pytest tests/test_payment.py
)

echo
echo "Packet preview (bugpacket show | head -40):"
echo
(
  cd examples/shopapp
  uv run --project ../.. bugpacket show | head -40
)
