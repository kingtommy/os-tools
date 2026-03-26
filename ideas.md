# os-tools — Ideas

## Context-switching helpers
- **AWS profile switcher** — widget showing active AWS profile with click-to-switch (edits ~/.aws/config or sets env vars)
- **Git branch ticker** — shows current branch + last commit age for key repos. Stale branches glow red. Click to open in terminal/IDE
- **Meeting countdown** — pulls next calendar event, shows countdown. Turns red at T-5min

## Awareness widgets (same bar as IP tray)
- **CPU/RAM/GPU mini-gauge** — tiny bars next to IP widget. Useful for builds, Docker, background game launchers
- **Port watcher** — shows listening ports, click to expand (IN PROGRESS)
- **Docker status** — running container count, click to see names, click to open logs

## Productivity
- **Clipboard history ring** — last N copied items, hotkey to cycle. Great for IPs, ARNs, UUIDs
- **Quick note/scratchpad** — hotkey popup sticky note, auto-saves. For jotting ticket numbers mid-context-switch
- **Focus timer** — Pomodoro-style, aware of alert apps. Discord/Battle.net during focus = wiggle warning

## Dev-specific
- **SSH tunnel manager** — like VPN widget but for SSH tunnels. Shows active tunnels, click connect/disconnect
- **Env indicator** — shows which environment you're pointing at (dev/staging/prod) based on env vars or config. Bright red for prod
