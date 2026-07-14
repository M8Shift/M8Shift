# How-to — macOS truecolour dashboard with iTerm2

M8Shift works in any terminal, but **iTerm2 is the recommended macOS terminal**
for the dashboard's reviewed 24-bit colour treatment. The repository includes a
GitHub Dark Dimmed colour preset whose ANSI colours match the semantic palette
used by `m8shift-top.py`.

The preset changes colours only. It does not replace your shell, font, keyboard
shortcuts, or other iTerm2 profile settings.

## Prerequisites

- macOS with [iTerm2](https://iterm2.com/) installed;
- an M8Shift checkout that contains `m8shift-top.py` and has already been
  initialized;
- Python 3.8 or newer.

## Import and select the colour preset

1. Open **iTerm2 → Settings → Profiles → Colors**.
2. Open **Color Presets…**, choose **Import…**, and select
   [`GitHub-Dark-Dimmed.itermcolors`](assets/terminal/GitHub-Dark-Dimmed.itermcolors).
3. Open **Color Presets…** again and select **GitHub Dark Dimmed** for the
   profile you use with M8Shift.
4. Open a new tab or window using that profile.

The preset contains the 16 ANSI colours plus the background, foreground,
cursor, selection, link, and bold colours. Its exact 24-bit values are recorded
in the [palette reference](assets/terminal/github-dark-dimmed-palette.md).

## Optional: make iTerm2 the default terminal

This step is **optional**. M8Shift and its truecolour dashboard work in iTerm2
without changing the macOS default terminal.

To make iTerm2 the application macOS opens for terminal requests, open the
**iTerm2** menu and choose **Make iTerm2 Default Term**.

You can perform the same menu action from Script Editor with this AppleScript:

```applescript
tell application id "com.googlecode.iterm2" to activate
tell application "System Events"
    tell application process "iTerm2"
        click menu item "Make iTerm2 Default Term" of menu 1 of menu bar item 2 of menu bar 1
    end tell
end tell
```

macOS may ask for Accessibility permission before Script Editor can control
iTerm2. To verify the change, reopen the **iTerm2** menu: **Make iTerm2 Default
Term** is disabled and **Make Terminal Default Term** is available. To revert
to Apple's Terminal, choose **Make Terminal Default Term**.

## Confirm truecolour detection

The imported preset controls how iTerm2 displays colours; it does not by itself
tell command-line programs which colour escape format to emit. M8Shift selects a
rendering tier from standard environment signals. Check the signals in the new
iTerm2 tab:

```bash
printf 'TERM=%s\nCOLORTERM=%s\n' "$TERM" "${COLORTERM:-<unset>}"
```

For the reviewed 24-bit tier, `COLORTERM` must be `truecolor` or `24bit`.
If it is unset, add this narrow declaration to your shell startup file and open
a new iTerm2 tab:

```bash
if [ "${TERM_PROGRAM:-}" = "iTerm.app" ]; then
  export COLORTERM=truecolor
fi
```

Keep iTerm2's reported terminal type at its normal `xterm-256color` setting.
The `TERM_PROGRAM` guard avoids advertising truecolour in a different terminal
that may not support it.

## Run the dashboard

From an initialized project root, run:

```bash
python3 m8shift-top.py
```

Press `q` to leave the dashboard. It is read-only: running it never claims the
relay pen or changes relay state.

## Why there are several colour tiers

Terminal themes and terminal colour capabilities are separate contracts. A
theme defines what colours look like; capability detection determines whether
M8Shift emits 24-bit RGB, xterm-256, ANSI-16, or no colour escapes.

This distinction closed the original truecolour gap in three steps:

- [issue #49](https://github.com/M8Shift/M8Shift/issues/49) added a deterministic
  xterm-256 fallback for the brand wordmark, so a non-truecolour terminal no
  longer lost the intended identity colours;
- [issue #50](https://github.com/M8Shift/M8Shift/issues/50) extended that model
  to the whole dashboard with semantic truecolour, xterm-256, ANSI-16, and plain
  tiers;
- [RFC 059](rfc/059-rfc-terminal-colour-capability-semantic-rendering.md)
  records the capability detector, exact semantic mapping, accessibility rules,
  and frame-width invariant.

The fallback is intentional. With `TERM=xterm-256color` and no recognized
`COLORTERM`, M8Shift emits deterministic 256-colour escapes. With neither signal,
it uses semantic ANSI-16 slots. `NO_COLOR` or `TERM=dumb` produces plain text.
Every tier retains labels, symbols, percentages, and state names, so colour is
never the only source of meaning.

## Documentation-site mirror

This page is the repository source for the macOS/iTerm2 setup. It must also be
mirrored into the separate VitePress documentation site published at
[m8shift.ai](https://m8shift.ai/). Updating that site, its repository remotes,
and its deployment is a separate release step; a repository-doc change is not
the site deployment.

## Troubleshooting

- **The dashboard uses the 256-colour tier:** re-check `COLORTERM` in the same
  tab that launches M8Shift. Do not set it globally for terminals that do not
  support 24-bit colour.
- **The dashboard has no colour:** check for `NO_COLOR`, `TERM=dumb`, or the
  `--plain` option. Those settings deliberately disable the dashboard renderer.
- **The imported colours do not appear:** confirm that GitHub Dark Dimmed is
  selected for the active iTerm2 profile, then open a new tab from that profile.
- **The layout changes when colour is disabled:** report a bug. RFC 059 requires
  every ANSI-stripped line to keep the selected frame width.
