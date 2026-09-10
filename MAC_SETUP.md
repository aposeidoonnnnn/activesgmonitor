# Running the scraper on your Mac via launchd (fallback)

Use this as a reliable fallback since GitHub Actions' `schedule` cron has
turned out to be intermittent on this account (fired once, then went
silent for hours — see README/session notes). launchd is used instead of
cron because it can wake a sleeping Mac and reliably restarts the job if
it dies. This runs independently of GitHub Actions — both can keep running
in parallel, and their CSVs can be merged later (same schema, just
concatenate and de-duplicate by timestamp+gym_name).

## 0. Prerequisites

Check you have git and Python 3 (macOS usually has both, but confirm):

```bash
git --version
python3 --version   # need 3.9+
```

If either is missing, install Xcode Command Line Tools (`xcode-select --install`)
for git, or `brew install python3` for Python.

## 1. Clone the repo and one-time setup

```bash
cd ~   # or wherever you want the project to live
git clone https://github.com/aposeidoonnnnn/activesgmonitor.git
cd activesgmonitor
git checkout claude/activesg-gym-crowd-scraper-slihpx

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

    <key>StartCalendarInterval</key>
    <array>
        <dict>
            <key>Hour</key>
            <integer>7</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>7</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>7</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>7</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>8</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>8</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>8</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>8</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>9</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>10</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>10</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>10</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>10</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>11</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>11</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>11</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>11</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>12</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>12</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>12</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>12</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>13</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>13</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>13</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>13</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>14</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>14</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>14</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>14</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>15</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>16</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>17</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>17</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>17</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>17</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>18</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>19</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>19</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>19</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>19</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>20</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>20</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>20</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>20</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>21</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>21</integer>
            <key>Minute</key>
            <integer>15</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>21</integer>
            <key>Minute</key>
            <integer>30</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>21</integer>
            <key>Minute</key>
            <integer>45</integer>
        </dict>
        <dict>
            <key>Hour</key>
            <integer>22</integer>
            <key>Minute</key>
            <integer>0</integer>
        </dict>
    </array>

    <key>StandardOutPath</key>
    <string>/Users/YOURNAME/activesgmonitor/data/launchd.out.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/YOURNAME/activesgmonitor/data/launchd.err.log</string>
</dict>
</plist>
```

`StartCalendarInterval` lists every 15-minute mark from 7:00am to 10:00pm
(61 entries) so the job only fires during ActiveSG's typical opening hours
instead of scraping uselessly overnight. **These times are your Mac's
local timezone** — if your Mac isn't set to Singapore time, adjust the
Hour values accordingly. No `RunAtLoad` here on purpose: with
StartCalendarInterval, loading the plist outside the 7am-10pm window
should not immediately fire a run.

If your Mac is asleep at a scheduled time, launchd runs the job as soon as
the Mac wakes (it does not skip missed runs), so don't be surprised by an
extra run right after your Mac wakes up.

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

## 4. The 30-day safeguard

`scrape.py` doesn't itself enforce the 30-day cutoff on your Mac (that logic
lives in the GitHub Actions workflow). On the Mac, the safeguard is: you
unload the job after 30 days (step 5). If you want it to also self-limit,
check `data/start_date.txt` (created by the first GitHub Actions run, or
you can create it yourself with `date -u +%Y-%m-%dT%H:%M:%SZ > data/start_date.txt`)
and compare against the current date before letting the job proceed.

## 5. Uninstall after the month is up

```bash
launchctl unload ~/Library/LaunchAgents/com.user.activesgmonitor.plist
rm ~/Library/LaunchAgents/com.user.activesgmonitor.plist
```

Your data stays in `data/crowd_log.csv` — nothing else needs cleanup.
