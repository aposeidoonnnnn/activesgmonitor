# Running the scraper on your Mac via launchd (fallback)

Use this only if GitHub Actions turns out to be Cloudflare-blocked (see
README for how that was verified). launchd is used instead of cron because
it can wake a sleeping Mac and reliably restarts the job if it dies.

## 1. One-time setup

```bash
cd ~/activesgmonitor   # wherever you cloned this repo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
deactivate
```

Confirm it works manually first:

```bash
source .venv/bin/activate
python scrape.py
tail data/crowd_log.csv
```

## 2. Install the launchd job

Create `~/Library/LaunchAgents/com.user.activesgmonitor.plist` with this
content. **Replace `/Users/YOURNAME/activesgmonitor` with the actual full
path to your clone of this repo** in all three places it appears.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.activesgmonitor</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOURNAME/activesgmonitor/.venv/bin/python3</string>
        <string>/Users/YOURNAME/activesgmonitor/scrape.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/YOURNAME/activesgmonitor</string>

    <key>StartInterval</key>
    <integer>900</integer>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/YOURNAME/activesgmonitor/data/launchd.out.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/YOURNAME/activesgmonitor/data/launchd.err.log</string>
</dict>
</plist>
```

`StartInterval` of `900` seconds = every 15 minutes. This is a one-shot job
that launchd relaunches every interval (not a long-running daemon), and
`RunAtLoad` means it also fires once immediately when loaded and again on
every login/wake.

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.user.activesgmonitor.plist
```

## 3. Check it's running

```bash
# Confirm launchd knows about it
launchctl list | grep com.user.activesgmonitor

# Watch the CSV grow
tail -f ~/activesgmonitor/data/crowd_log.csv

# Check logs for errors
tail -f ~/activesgmonitor/data/launchd.err.log
```

`launchctl list` should show a PID (or `-` between runs) and a last exit
code of `0`. A non-zero code means the last run failed — check
`data/launchd.err.log` and `data/run_log.txt`.

## 4. The 7-day safeguard

`scrape.py` doesn't itself enforce the 7-day cutoff on your Mac (that logic
lives in the GitHub Actions workflow). On the Mac, the safeguard is: you
unload the job after 7 days (step 5). If you want it to also self-limit,
check `data/start_date.txt` (created by the first GitHub Actions run, or
you can create it yourself with `date -u +%Y-%m-%dT%H:%M:%SZ > data/start_date.txt`)
and compare against the current date before letting the job proceed.

## 5. Uninstall after the week is up

```bash
launchctl unload ~/Library/LaunchAgents/com.user.activesgmonitor.plist
rm ~/Library/LaunchAgents/com.user.activesgmonitor.plist
```

Your data stays in `data/crowd_log.csv` — nothing else needs cleanup.
