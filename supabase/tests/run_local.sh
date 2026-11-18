#!/usr/bin/env bash
# Şemayı geçici bir yerel PostgreSQL üzerinde test eder.
# Kullanım: supabase/tests/run_local.sh   (initdb/pg_ctl PATH'te veya /usr/lib/postgresql/*/bin altında olmalı)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../.."
PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
export PATH="$PGBIN:$PATH"
TMP="$(mktemp -d)"
PORT=${PGPORT_TEST:-54329}
cleanup() { pg_ctl -D "$TMP/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
RUNAS=()
if [ "$(id -u)" = "0" ]; then chown -R postgres "$TMP"; RUNAS=(runuser -u postgres --); fi
"${RUNAS[@]}" initdb -D "$TMP/data" -U postgres -A trust >/dev/null
"${RUNAS[@]}" pg_ctl -D "$TMP/data" -o "-p $PORT -k $TMP -c listen_addresses=''" -l "$TMP/log" start >/dev/null
PSQL=(psql -h "$TMP" -p "$PORT" -U postgres -d postgres -q -v ON_ERROR_STOP=1)
"${PSQL[@]}" -f "$HERE/supabase_stub.sql"
for f in "$ROOT"/supabase/migrations/*.sql; do echo "migration: $(basename "$f")"; "${PSQL[@]}" -f "$f"; done
# migration'ları iki kez çalıştırmak hata vermemeli (idempotent)
for f in "$ROOT"/supabase/migrations/*.sql; do "${PSQL[@]}" -f "$f"; done
"${PSQL[@]}" -f "$ROOT/supabase/seed.sql"
"${PSQL[@]}" -f "$HERE/rls_test.sql"
