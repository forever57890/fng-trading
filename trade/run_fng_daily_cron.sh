#!/usr/bin/env bash
# Run FNG daily trader once (for crontab at UTC 00:00).
# Example:
#   0 0 * * * /bin/bash /path/to/dashboard/fng_trading/trade/run_fng_daily_cron.sh >> /path/to/dashboard/fng_trading/trade/runtime/fng_cron.log 2>&1

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

export FNG_DRY_RUN=0
export FNG_USE_MA_TP=1
export FNG_MA_DAYS=90
export FNG_ORDER_QTY=0.001
export FNG_RUN_MODE=once

FNG_ENV="$PROJECT_ROOT/fng_trading/.env"
ROOT_ENV="$PROJECT_ROOT/.env"

for env_file in "$FNG_ENV" "$ROOT_ENV"; do
  if [ -f "$env_file" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$env_file"
    set +a
  fi
done

# Prefer project venv when present
if [ -x "$PROJECT_ROOT/.venv/bin/python3" ]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python3"
else
  PYTHON="python3"
fi

"$PYTHON" -m fng_trading.trade.fng_daily_trader
