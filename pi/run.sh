#!/usr/bin/env bash
#
# Raspberry Pi cron wrapper for Market-Bias.
#
# Does the same thing the GitHub Actions workflows did, but on the Pi:
#   1. sync with GitHub  (git pull --rebase)   -- best effort, never fatal
#   2. run the python script inside the project's venv
#   3. commit + push the updated db/weights     -- best effort, never fatal
#
# Usage:  run.sh daily   ->  run_daily.py
#         run.sh eval    ->  run_evaluation.py
#         run.sh weekly  ->  run_weekly.py
#
set -uo pipefail

# cron runs with a bare PATH; make sure git/python/etc. are findable.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH:-}"

MODE="${1:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR" || { echo "FATAL: cannot cd to $REPO_DIR"; exit 1; }

LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

case "$MODE" in
  daily)  SCRIPT="run_daily.py";      LOG="$LOG_DIR/daily.log" ;;
  eval)   SCRIPT="run_evaluation.py"; LOG="$LOG_DIR/evaluation.log" ;;
  weekly) SCRIPT="run_weekly.py";     LOG="$LOG_DIR/weekly.log" ;;
  *) echo "Usage: $0 daily|eval|weekly" >&2; exit 2 ;;
esac

# Prefer the project venv; fall back to system python3 if it's missing.
PY="$REPO_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') :: $MODE ====="

  if [ -d "$REPO_DIR/.git" ]; then
    git pull --rebase --autostash || echo "WARN: git pull failed (continuing offline)"
  fi

  "$PY" "$SCRIPT"
  STATUS=$?
  echo "script exit status: $STATUS"

  if [ -d "$REPO_DIR/.git" ]; then
    git add -f memory/daily_log.db 2>/dev/null || true
    git add config/signal_weights.json 2>/dev/null || true
    if ! git diff --cached --quiet; then
      git commit -m "Update memory + weights ($MODE, pi)" || true
      git push || echo "WARN: git push failed (state saved locally, will sync next run)"
    else
      echo "No changes to commit"
    fi
  fi

  echo "===== done $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  echo
} >> "$LOG" 2>&1
