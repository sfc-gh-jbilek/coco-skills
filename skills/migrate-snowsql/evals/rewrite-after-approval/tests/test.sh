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
7dc94ac66d54488794f3b261f1ebdb509884d68c0418891c50705708028aa1a5  continue.sql
eaa3f778fa8a94beb0f95af9b286b014ad434cb31c5ef60cae1b2c222745f874  daily.sh
9a0bec8b7142c3502f086002f2bb849204056cfc5ba703612f0d3bf1ebefe051  daily.sql
EOF

test -f snowsql-migrated/daily.sh || fail "missing translated daily.sh"
test -f snowsql-migrated/daily.sql || fail "missing translated daily.sql"
grep -q 'snow sql' snowsql-migrated/daily.sh || fail "daily.sh was not translated"
grep -E -q '<%[[:space:]]*day[[:space:]]*%>' snowsql-migrated/daily.sql || fail "day variable was not rewritten"
if find snowsql-migrated -type f \( -name 'continue.sh' -o -name 'continue.sql' \) | grep -q .; then
  fail "blocked file was copied"
fi
test -f snowsql-migration-report.md || fail "missing report"
grep -q 'STATUS: COPIES_WRITTEN' snowsql-migration-report.md || fail "missing copies token"
grep -q 'DISPOSITION: blocked' snowsql-migration-report.md || fail "missing blocked token"

echo "PASS"
echo 1 > /logs/verifier/reward.txt
