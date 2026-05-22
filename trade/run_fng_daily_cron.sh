#!/usr/bin/env bash
# Run FNG daily trader once (for crontab or launchd at UTC 00:00).
#
# Crontab (no redirect needed — script writes fng_cron.log itself):
#   TZ=UTC
#   0 0 * * * /bin/bash /path/to/fng_trading/trade/run_fng_daily_cron.sh
#
# Optional env:
#   FNG_PYTHON=/path/to/python3   (cron PATH is minimal; must have pandas)
#   FNG_CRON_LOG=/path/to/fng_cron.log
#   FNG_PRINT_JSON=1            (default 0 here: cron log stays readable)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Parent of repo root must be on PYTHONPATH for `python -m fng_trading.*`
PKG_PARENT="$(cd "$REPO_ROOT/.." && pwd)"

RUNTIME_DIR="${FNG_RUNTIME_DIR:-$SCRIPT_DIR/runtime}"
CRON_LOG="${FNG_CRON_LOG:-$RUNTIME_DIR/fng_cron.log}"
mkdir -p "$RUNTIME_DIR"

# Self-log: crontab ">> file" can fail if runtime/ did not exist yet (macOS cron).
exec >>"$CRON_LOG" 2>&1

echo "[cron] ===== $(date -u +%Y-%m-%dT%H:%M:%SZ) start ====="
echo "[cron] script=$0 user=$(whoami 2>/dev/null || id -un) pwd=$(pwd)"

export PYTHONPATH="${PKG_PARENT}:${PYTHONPATH:-}"
cd "$PKG_PARENT"
echo "[cron] cd=$PKG_PARENT PYTHONPATH=$PYTHONPATH"

export FNG_DRY_RUN=0
export FNG_USE_MA_TP=1
export FNG_MA_DAYS=90
export FNG_ORDER_QTY=0.001
export FNG_RUN_MODE=once
export FNG_PRINT_JSON="${FNG_PRINT_JSON:-0}"

if [ -f "$REPO_ROOT/.env" ]; then
  echo "[cron] source $REPO_ROOT/.env"
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

resolve_python() {
  if [ -n "${FNG_PYTHON:-}" ] && [ -x "$FNG_PYTHON" ]; then
    echo "$FNG_PYTHON"
    return 0
  fi
  local candidate
  for candidate in \
    "$REPO_ROOT/.venv/bin/python3" \
    "$PKG_PARENT/.venv/bin/python3" \
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3" \
    "$(command -v python3 2>/dev/null || true)" \
    /usr/bin/python3
  do
    [ -n "$candidate" ] || continue
    [ -x "$candidate" ] || continue
    if "$candidate" -c "import pandas" 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

if ! PYTHON="$(resolve_python)"; then
  echo "[cron] ERROR: no python3 with pandas found. Set FNG_PYTHON or install deps."
  echo "[cron] ===== $(date -u +%Y-%m-%dT%H:%M:%SZ) done exit=127 ====="
  exit 127
fi

echo "[cron] python=$PYTHON repo=$REPO_ROOT log=$CRON_LOG"

if [ -n "${FNG_SIGNAL_DAY:-}" ]; then
  echo "[cron] WARN: FNG_SIGNAL_DAY=${FNG_SIGNAL_DAY} is set — unset for live daily cron"
fi

set +e
"$PYTHON" -m fng_trading.trade.fng_daily_trader
exit_code=$?
set -e

echo "[cron] ===== $(date -u +%Y-%m-%dT%H:%M:%SZ) done exit=$exit_code ====="
exit "$exit_code"
