#!/bin/bash
# Start the development Postgres for the platform and make sure its
# database exists. Called by session-start.sh; idempotent, so it is safe to
# run at the start of every session. Its own process, so `set -e` here
# stops this script on the first failure without stopping the session.
set -euo pipefail

PG_BIN=/usr/lib/postgresql/16/bin
PGDATA=/var/lib/postgresql/vpdev
SOCKET=/var/run/postgresql

if [ ! -x "$PG_BIN/pg_ctl" ]; then
  echo "postgres 16 is not installed; the platform's database tests will skip"
  exit 0
fi

# The package normally creates this user; create it if an image did not.
id postgres >/dev/null 2>&1 || useradd -r -s /bin/bash -d /var/lib/postgresql postgres
mkdir -p "$PGDATA" "$SOCKET"
chown -R postgres:postgres "$PGDATA" "$SOCKET"

# A fresh container has no cluster; a restarted one keeps its data here.
# Trust authentication is local to this container: the server listens on
# its socket and localhost only.
if [ ! -f "$PGDATA/PG_VERSION" ]; then
  su postgres -c "$PG_BIN/initdb -D $PGDATA -A trust -U postgres" >/dev/null
fi

if ! pg_isready -q -h "$SOCKET"; then
  su postgres -c "$PG_BIN/pg_ctl -D $PGDATA -l $PGDATA/server.log -o '-p 5432 -k $SOCKET' -w start" >/dev/null
fi

# vp_dev for the running service; vp_test for the test suite, whose fixtures
# clear queues and halts and must never touch what the service is using.
for db in vp_dev vp_test; do
  if ! su postgres -c "psql -h $SOCKET -tAc \"select 1 from pg_database where datname = '$db'\"" | grep -q 1; then
    su postgres -c "createdb -h $SOCKET $db"
  fi
done
