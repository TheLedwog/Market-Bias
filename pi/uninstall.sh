#!/usr/bin/env bash
#
# Market-Bias :: Raspberry Pi uninstaller
#
# Removes ONLY the cron jobs this project installed. Leaves your repo, venv,
# .env, database and weights completely intact. Use this when reverting to
# GitHub Actions (then re-enable the workflows in the Actions tab).
#
#     bash pi/uninstall.sh
#
set -euo pipefail

MARK_BEGIN="# >>> market-bias (pi) >>>"
MARK_END="# <<< market-bias (pi) <<<"

if ! crontab -l 2>/dev/null | grep -qF "$MARK_BEGIN"; then
  echo ">> No market-bias cron jobs found. Nothing to do."
  exit 0
fi

crontab -l 2>/dev/null | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
  $0==b {skip=1}
  skip==0 {print}
  $0==e {skip=0}
' | crontab -

echo ">> Removed market-bias cron jobs."
echo "   venv, .env, database and weights were left untouched."
echo "   To fully revert: re-enable the daily/evaluation workflows in the GitHub Actions tab."
