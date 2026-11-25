#!/usr/bin/env bash
# Local end-to-end environment for the orders review flow. See e2e/README.md.
#
#   e2e/run.sh reset [--with-orders]   fresh database, seeded user + products (+ ready orders)
#   e2e/run.sh up                      start fake WhatsApp, Django, Celery worker, Streamlit
#   e2e/run.sh down                    stop them
#   e2e/run.sh status                  what is running, last log lines
#   e2e/run.sh outbox                  messages the fake WhatsApp received
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/e2e/.data"
PIDS="$DATA/pids"
LOGS="$DATA/logs"
PY="$ROOT/venv/bin/python"
CELERY="$ROOT/venv/bin/celery"
STREAMLIT="$ROOT/orders_streamlit/venv-ordersui/bin/streamlit"

DJANGO_PORT="${E2E_DJANGO_PORT:-8001}"
UI_PORT="${E2E_UI_PORT:-8502}"
FAKE_WA_PORT="${E2E_FAKE_WA_PORT:-8999}"

export DJANGO_SETTINGS_MODULE=whatsapp_campaign.settings_e2e
export PYTHONUNBUFFERED=1

if [[ "${E2E_REAL_WHATSAPP:-}" == "1" ]]; then
  if [[ -z "${E2E_SEND_TO:-}" ]]; then
    echo "E2E_REAL_WHATSAPP=1 needs E2E_SEND_TO=<your number, e.g. 9198xxxxxxxx>" >&2; exit 1
  fi
  WA_MODE="REAL 360dialog, only to: $E2E_SEND_TO"
else
  # decouple reads the environment before .env, so this keeps every send local
  export WHATSAPP_360_API_URL="http://127.0.0.1:$FAKE_WA_PORT"
  export WHATSAPP_360_API_KEY="e2e-fake-key"
  WA_MODE="fake (e2e/.data/whatsapp_outbox)"
fi

mkdir -p "$PIDS" "$LOGS"

start() {  # name, command...
  local name="$1"; shift
  if [[ -f "$PIDS/$name.pid" ]] && kill -0 "$(cat "$PIDS/$name.pid")" 2>/dev/null; then
    echo "  $name already running"; return
  fi
  nohup "$@" >"$LOGS/$name.log" 2>&1 &
  echo $! >"$PIDS/$name.pid"
  echo "  $name started (log: e2e/.data/logs/$name.log)"
}

stop_all() {
  for f in "$PIDS"/*.pid; do
    [[ -e "$f" ]] || continue
    local pid; pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; echo "  stopped $(basename "$f" .pid)"; fi
    rm -f "$f"
  done
}

case "${1:-}" in
  reset)
    stop_all
    rm -rf "$DATA"
    cd "$ROOT"
    "$PY" manage.py migrate --noinput >/dev/null
    "$PY" manage.py seed_e2e ${2:-}
    echo "Fresh E2E database at e2e/.data/db.sqlite3"
    ;;
  up)
    [[ -f "$DATA/db.sqlite3" ]] || { echo "No E2E database yet: run e2e/run.sh reset first" >&2; exit 1; }
    cd "$ROOT"
    [[ "${E2E_REAL_WHATSAPP:-}" == "1" ]] || start fake_whatsapp "$PY" -m e2e.fake_whatsapp --port "$FAKE_WA_PORT" --outbox "$DATA/whatsapp_outbox"
    start django "$PY" manage.py runserver "127.0.0.1:$DJANGO_PORT" --noreload
    start celery "$CELERY" -A whatsapp_campaign worker --pool=solo --loglevel=INFO
    (cd "$ROOT/orders_streamlit" && export API_BASE_URL="http://127.0.0.1:$DJANGO_PORT/api" &&
      start streamlit "$STREAMLIT" run app.py --server.port "$UI_PORT" --server.address 127.0.0.1 --server.headless true)
    echo
    echo "Orders UI:  http://localhost:$UI_PORT   (login e2e / e2e-pass-123)"
    echo "API:        http://127.0.0.1:$DJANGO_PORT/api/   admin: http://127.0.0.1:$DJANGO_PORT/admin/"
    echo "WhatsApp:   $WA_MODE"
    ;;
  down)
    stop_all
    ;;
  status)
    for f in "$PIDS"/*.pid; do
      [[ -e "$f" ]] || { echo "nothing running"; break; }
      n="$(basename "$f" .pid)"
      if kill -0 "$(cat "$f")" 2>/dev/null; then echo "$n: running"; else echo "$n: DEAD"; fi
      tail -n 3 "$LOGS/$n.log" 2>/dev/null | sed 's/^/    /'
    done
    ;;
  outbox)
    ls -1 "$DATA/whatsapp_outbox" 2>/dev/null || echo "no messages yet"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 1
    ;;
esac
