# Running DailyGrad on a schedule

DailyGrad is a short batch job: it runs, writes its files, unloads the model and exits.
Any scheduler can run it. Three things matter for all of them:

- **Use absolute paths.** A relative `data_dir` resolves against the working directory,
  which is rarely what a scheduler uses. Set `data_dir` to an absolute path in your config
  file, and point to that file with `--config` or `DAILYGRAD_CONFIG`.
- **Ollama must be running** at the configured endpoint when the job starts.
- **Check the exit code.** 0 is a normal digest, 1 is a degraded digest or a crash, 2 is a
  configuration error. See [output.md](output.md).

Running more than once a day is safe: stories are not repeated, and the micro-lesson stays
the same until the next calendar day.

The examples assume DailyGrad is installed in a virtual environment at
`/home/you/dailygrad/.venv` with its config at `/home/you/dailygrad/dailygrad.toml`.
Replace both with your own paths. `dailygrad config --config <file>` shows where the
output will go.

## cron

Run at 07:00 every day and keep the log:

```cron
0 7 * * * /home/you/dailygrad/.venv/bin/dailygrad run --config /home/you/dailygrad/dailygrad.toml >/dev/null 2>>/home/you/dailygrad/dailygrad.log
```

The digest on stdout is discarded here because it is also saved as `latest.md`. To have
cron mail you the digest instead, drop `>/dev/null` and set `MAILTO`.

## systemd timer

`~/.config/systemd/user/dailygrad.service`:

```ini
[Unit]
Description=DailyGrad daily AI briefing

[Service]
Type=oneshot
ExecStart=/home/you/dailygrad/.venv/bin/dailygrad run --config /home/you/dailygrad/dailygrad.toml
StandardOutput=null
```

`~/.config/systemd/user/dailygrad.timer`:

```ini
[Unit]
Description=Run DailyGrad every morning

[Timer]
OnCalendar=*-*-* 07:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it and check on it:

```sh
systemctl --user daemon-reload
systemctl --user enable --now dailygrad.timer
systemctl --user list-timers dailygrad.timer
journalctl --user -u dailygrad.service
```

`Persistent=true` runs a missed job after the machine wakes or boots. A degraded run exits
with 1, so systemd reports the unit as failed even though the digest was written.

## macOS launchd

`~/Library/LaunchAgents/com.example.dailygrad.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.dailygrad</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/dailygrad/.venv/bin/dailygrad</string>
    <string>run</string>
    <string>--config</string>
    <string>/Users/you/dailygrad/dailygrad.toml</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/dev/null</string>
  <key>StandardErrorPath</key>
  <string>/Users/you/dailygrad/dailygrad.log</string>
</dict>
</plist>
```

Load it:

```sh
launchctl load ~/Library/LaunchAgents/com.example.dailygrad.plist
```

launchd runs a missed job when the Mac next wakes. The Ollama app must be running.
