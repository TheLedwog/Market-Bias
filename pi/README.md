# Running Market-Bias on a Raspberry Pi

This moves the **scheduling** off GitHub Actions and onto your Pi.


## One-time setup

On the Pi:

```bash
# 1. Clone your repo (use SSH or a token so the Pi can push back)
git clone git@github.com:<you>/Market-Bias.git
cd Market-Bias

# 2. (recommended) make the Pi match the original London schedule + DST
sudo timedatectl set-timezone Europe/London

# 3. Install: venv, deps, .env template, and the cron jobs
bash pi/install.sh

# 4. Put your keys in the .env the installer created
nano .env        # OPENAI_API_KEY, NEWS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 5. Smoke-test a run by hand (then check the log)
pi/run.sh daily
cat pi/logs/daily.log
```

### Make sure the Pi can push to GitHub

The wrapper commits the updated `daily_log.db` + `signal_weights.json` and
pushes them. For that to work the clone needs push access:

- **SSH (simplest):** clone with `git@github.com:...` and add the Pi's SSH key
  to your GitHub account, **or**
- **HTTPS + token:** clone with `https://...` and configure a credential helper
  / personal access token.

If push isn't set up the run still completes and posts to Telegram — it just
keeps the state locally and warns in the log. It'll push once credentials work.

## Schedule

Installed cron jobs (Pi local time):

| Job        | When                          | Command             |
|------------|-------------------------------|---------------------|
| Daily bias | weekdays **14:30**            | `pi/run.sh daily`   |
| Evaluation | weekdays **22:30, 23:30, 01:30** | `pi/run.sh eval` |

These mirror the original workflow times. Edit them with `crontab -e` (look for
the `# >>> market-bias (pi) >>>` block) if you want different times.

## Avoiding double runs

While the Pi is in charge, **disable the two GitHub Actions workflows** so they
don't also fire and double-post:

> GitHub repo → **Actions** tab → *Daily US Futures Bias* → **···** → **Disable workflow**
> (repeat for *US Futures Evaluation*)

This is reversible with one click and changes no files.

## Reverting to GitHub Actions

```bash
bash pi/uninstall.sh     # removes the cron jobs (keeps venv/.env/db/weights)
```

Then re-enable both workflows in the Actions tab. Done — no code to undo.

## Logs

```
pi/logs/daily.log
pi/logs/evaluation.log
```

Each run appends a timestamped block with the script output, exit status, and
git sync result.
