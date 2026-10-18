#!/bin/bash
fail() {
  echo "FAIL: $1"
  mkdir -p /logs/verifier
  echo 0 > /logs/verifier/reward.txt
  exit 1
}
mkdir -p /logs/verifier
cd /workspace || fail "workspace missing"

sha256sum -c <<'EOF' || fail "originals changed"
edb2a8244089e3f58b61b6eaffd31a8773f531ba5749c7da2d3eb987c438efc3  continue.sh
e45e3a75467b8ba38b44787e32bf3e1a1edcd7033a9bd544d622b733c10560f5  continue.sql
0b88b2f568a9fba1624d0c78f4de3193849869f3c950c1bfeea9864ff176a596  export.sh
40588adc639499c4a652d12a387c0b03d2d4500a4e8208d6687c2da4eb8ce834  extract.sql
EOF

test -f snowsql-inventory.json || fail "missing inventory"
test -f snowsql-migration-report.md || fail "missing report"
grep -q 'DISPOSITION: blocked' snowsql-migration-report.md || fail "missing blocked token"
grep -q 'COPY INTO @stage' snowsql-migration-report.md || fail "missing COPY INTO"
grep -q 'snow stage copy' snowsql-migration-report.md || fail "missing stage copy"

python3 - <<'PY' || fail "inventory dispositions"
import json
from pathlib import Path
data = json.loads(Path("snowsql-inventory.json").read_text())
names = {
    (item.get("name"), item.get("disposition"))
    for item in data["findings"]
}
if ("exit_on_error", "blocked") not in names:
    raise SystemExit("continue")
if ("large-result", "blocked") not in names:
    raise SystemExit("large")
if ("!set", "blocked") not in names:
    raise SystemExit("set")
PY

if [ -f snowsql-migrated/export.sh ]; then
  grep -q 'COPY INTO @stage' snowsql-migrated/export.sh || fail "export copy dropped COPY INTO"
  grep -q 'snow stage copy' snowsql-migrated/export.sh || fail "export copy dropped stage copy"
fi

echo "PASS"
echo 1 > /logs/verifier/reward.txt
