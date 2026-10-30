#!/bin/sh
# Private PostgreSQL for development and tests: its own data folder (.pgdata)
# and port (54329), so it never touches any other Postgres on this machine.
#   scripts/dev_db.sh start | stop | status
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/.pgdata"
PORT=54329
case "${1:-start}" in
  start)
    if [ ! -d "$DIR" ]; then
      initdb -D "$DIR" -U billchecker --auth=trust --no-instructions >/dev/null
    fi
    pg_ctl -D "$DIR" -o "-p $PORT -k /tmp -c listen_addresses=127.0.0.1" -l "$DIR/server.log" -w start >/dev/null
    createdb -h 127.0.0.1 -p $PORT -U billchecker billchecker 2>/dev/null || true
    createdb -h 127.0.0.1 -p $PORT -U billchecker billchecker_test 2>/dev/null || true
    echo "postgres running: postgresql://billchecker@127.0.0.1:$PORT/billchecker"
    ;;
  stop) pg_ctl -D "$DIR" -w stop >/dev/null && echo stopped ;;
  status) pg_ctl -D "$DIR" status ;;
esac
