#!/usr/bin/env bash
#
# Market-Bias :: Raspberry Pi installer
#
# Sets up a local venv, installs deps, creates a .env template, and installs
# two cron jobs that run the daily bias + evaluation on a schedule -- replacing
# GitHub Actions. Safe to re-run (idempotent). Nothing here touches the bot's
# code or the .github workflows, so you can always revert to Actions.
#
# Run on the Pi from inside the cloned repo:
#     bash pi/install.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo ">> Market-Bias Raspberry Pi installer"
echo ">> Repo: $REPO_DIR"

# ---------------------------------------------------------------------------
# 1. Python + virtualenv
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found."
  echo "       Install it with: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 1
fi

if [ ! -d "$REPO_DIR/.venv" ]; then
  echo ">> Creating virtualenv at .venv"
  python3 -m venv "$REPO_DIR/.venv"
fi

echo ">> Installing dependencies"
"$REPO_DIR/.venv/bin/pip" install --upgrade pip >/dev/null
"$REPO_DIR/.venv/bin/pip" install -r "$REPO_DIR/requirements.txt"

# ---------------------------------------------------------------------------
# 2. .env template (the scripts read keys from here via python-dotenv)
# ---------------------------------------------------------------------------
if [ ! -f "$REPO_DIR/.env" ]; then
  echo ">> Creating .env template (fill in your keys before the first run)"
  cat > "$REPO_DIR/.env" <<'EOF'
OPENAI_API_KEY=
NEWS_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
  echo "   -> edit $REPO_DIR/.env"
else
  echo ">> .env already exists -- leaving it untouched"
fi

# ---------------------------------------------------------------------------
# 3. git identity for the Pi's commits (repo-local, only if not already set)
# ---------------------------------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" config user.name  >/dev/null 2>&1 || git -C "$REPO_DIR" config user.name  "market-bias-pi"
  git -C "$REPO_DIR" config user.email >/dev/null 2>&1 || git -C "$REPO_DIR" config user.email "market-bias-pi@localhost"
fi

# ---------------------------------------------------------------------------
# 4. wrapper executable
# ---------------------------------------------------------------------------
chmod +x "$SCRIPT_DIR/run.sh"

# ---------------------------------------------------------------------------
# 5. cron jobs (idempotent, delimited by markers so uninstall can remove them)
#    Times are the Pi's LOCAL time. Set the Pi to Europe/London with
#        sudo timedatectl set-timezone Europe/London
#    to match the original workflow schedule and get automatic DST handling.
# ---------------------------------------------------------------------------
MARK_BEGIN="# >>> market-bias (pi) >>>"
MARK_END="# <<< market-bias (pi) <<<"
RUN="$SCRIPT_DIR/run.sh"

CRON_BLOCK="$MARK_BEGIN
# Daily bias  -- weekdays 14:30 local
30 14 * * 1-5 $RUN daily
# Evaluation  -- weekdays 22:30, 23:30, 01:30 local (retry slots for late data)
30 1,22,23 * * 1-5 $RUN eval
$MARK_END"

# Strip any previous block, then append the fresh one.
# `|| true` so an empty/absent crontab (crontab -l exits non-zero) doesn't trip set -e.
NEW_CRON="$( { crontab -l 2>/dev/null || true; } | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '
  $0==b {skip=1}
  skip==0 {print}
  $0==e {skip=0}
')"

printf '%s\n%s\n' "$NEW_CRON" "$CRON_BLOCK" | sed '/^$/N;/^\n$/D' | crontab -

echo ">> Installed cron jobs:"
crontab -l | awk -v b="$MARK_BEGIN" -v e="$MARK_END" '$0==b{p=1} p{print} $0==e{p=0}'

echo ""
echo ">> Done."
echo "   Next steps:"
echo "     1. Edit $REPO_DIR/.env with your API keys (if you haven't)."
echo "     2. Set the Pi timezone:  sudo timedatectl set-timezone Europe/London"
echo "     3. Test a run now:       $RUN daily   (then check pi/logs/daily.log)"
echo "     4. Disable the two GitHub Actions workflows in the Actions tab"
echo "        (so they don't double-post). Re-enable them to revert."
