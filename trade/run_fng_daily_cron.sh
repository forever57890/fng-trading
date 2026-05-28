#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

RUNTIME_DIR="${FNG_RUNTIME_DIR:-$SCRIPT_DIR/runtime}"
CRON_LOG="${FNG_CRON_LOG:-$RUNTIME_DIR/fng_cron.log}"
mkdir -p "$RUNTIME_DIR"
exec >>"$CRON_LOG" 2>&1

echo "[cron] ===== $(date -u +%Y-%m-%dT%H:%M:%SZ) start ====="
echo "[cron] script=$0 user=$(whoami 2>/dev/null || id -un) pwd=$(pwd)"

if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
fi

export FNG_DRY_RUN="${FNG_DRY_RUN:-0}"
export FNG_USE_MA_TP="${FNG_USE_MA_TP:-1}"
export FNG_MA_DAYS="${FNG_MA_DAYS:-90}"
export FNG_ORDER_QTY="${FNG_ORDER_QTY:-0.001}"
export FNG_RUN_MODE="${FNG_RUN_MODE:-once}"
export FNG_PRINT_JSON="${FNG_PRINT_JSON:-0}"

resolve_python() {
  if [ -n "${FNG_PYTHON:-}" ] && [ -x "$FNG_PYTHON" ]; then
    echo "$FNG_PYTHON"; return 0
  fi
  for candidate in \
    "$REPO_ROOT/.venv/bin/python3" \
    "$REPO_ROOT/../.venv/bin/python3" \
    "$(command -v python3 2>/dev/null || true)"
  do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if "$candidate" -c "import pandas" 2>/dev/null; then
      echo "$candidate"; return 0
    fi
  done
  return 1
}

resolve_module() {
  local roots=("$REPO_ROOT" "$REPO_ROOT/.." "$(pwd)")
  local root
  for root in "${roots[@]}"; do
    [ -d "$root" ] || continue
    if [ -f "$root/fng_trading/trade/fng_daily_trader.py" ]; then
      echo "$root|fng_trading.trade.fng_daily_trader|package"
      return 0
    fi
    if [ -f "$root/trade/fng_daily_trader.py" ]; then
      echo "$root|trade.fng_daily_trader|flat"
      return 0
    fi
  done
  return 1
}

PYTHON="$(resolve_python)" || {
  echo "[cron] ERROR: no python3 with pandas found"
  exit 127
}

module_info="$(resolve_module)" || {
  echo "[cron] ERROR: cannot locate fng_daily_trader module root"
  exit 127
}

MODULE_ROOT="${module_info%%|*}"
rest="${module_info#*|}"
ENTRY_MODULE="${rest%%|*}"
LAYOUT_MODE="${module_info##*|}"
export MODULE_ROOT

export PYTHONPATH="${MODULE_ROOT}:${PYTHONPATH:-}"
cd "$MODULE_ROOT"

echo "[cron] python=$PYTHON repo=$MODULE_ROOT entry_module=$ENTRY_MODULE layout=$LAYOUT_MODE"

set +e
if [ "$LAYOUT_MODE" = "flat" ]; then
  "$PYTHON" - <<'PYCODE'
import os, runpy, sys, types
root = os.environ["MODULE_ROOT"]
pkg = types.ModuleType("fng_trading")
pkg.__path__ = [root]
sys.modules["fng_trading"] = pkg
runpy.run_module("trade.fng_daily_trader", run_name="__main__")
PYCODE
else
  "$PYTHON" -m "$ENTRY_MODULE"
fi
exit_code=$?
set -e

echo "[cron] ===== $(date -u +%Y-%m-%dT%H:%M:%SZ) done exit=$exit_code ====="
exit "$exit_code"