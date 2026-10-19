#!/bin/bash
fail() {
  echo "FAIL: $1"
  mkdir -p /logs/verifier
  echo 0 > /logs/verifier/reward.txt
  exit 1
}
mkdir -p /logs/verifier
cd /workspace || fail "workspace missing"

sha256sum -c <<'EOF' || fail "notes.txt changed"
60812b7cdf86570bd6e9310c1df248dea28c74300a17b03c233a827468e27057  notes.txt
EOF

test -s answer.txt || fail "missing answer.txt"
test ! -e snowsql-inventory.json || fail "migration inventory was created"
test ! -e snowsql-migration-report.md || fail "migration report was created"
test ! -e migration-plan.md || fail "migration plan was created"
test ! -d snowsql-migrated || fail "migration copies were created"
test ! -d snowsql-migration || fail "migration working directory was created"

echo "PASS"
echo 1 > /logs/verifier/reward.txt
