<h1 align="center">mouseferry</h1>

<p align="center">
  <em>Seamless mouse sharing between a Linux PC and an Android device, powered by <a href="https://github.com/Genymobile/scrcpy">scrcpy</a>.</em>
</p>

<p align="center">
  <img alt="License: PolyForm Noncommercial 1.0.0" src="https://img.shields.io/badge/license-PolyForm%20NC%201.0.0-blue.svg">
  <img alt="Python 3.8+" src="https://img.shields.io/badge/python-3.8%2B-blue.svg">
  <img alt="Platform: Linux/X11" src="https://img.shields.io/badge/platform-Linux%20%7C%20X11-lightgrey.svg">
  <img alt="Status: beta" src="https://img.shields.io/badge/status-beta-orange.svg">
</p>

---

## What it does

Put your Android phone or tablet next to your Linux PC and use it as a **second screen you drive with your PC's mouse**:

- Move the mouse past the **left** (or **right**) edge of your monitor → the cursor is *ferried* to the Android device. A scrcpy session spins up on demand, the pointer appears on Android via UHID, and you control the device naturally with your mouse and keyboard.
- Sweep the mouse decisively back toward the PC → scrcpy is killed cleanly and the pointer lands back on your desktop. No ghost cursor, no stuck window.

Think *Synergy / Barrier / Logitech Flow*, but **PC ↔ Android**, without installing anything on the phone beyond enabling USB/ADB debugging.

## Why it exists

scrcpy already supports high-quality mirroring and UHID mouse injection, but the moment SDL grabs your pointer you need a special keystroke to get it back, and the UHID cursor tends to linger. `mouseferry` wraps scrcpy with two ideas:

1. **Edge-trigger entry** via `xdotool` polling — the mouse itself becomes the "switch to phone" gesture.
2. **Sweep-return detection via evdev** — the only mechanism that keeps working *while scrcpy has grabbed the SDL pointer*. A quick flick of the wrist back toward the PC is enough; the evdev tracker sums the relative X deltas in a short window and, past the configured threshold, kills scrcpy and warps the cursor back to the desktop.

## Requirements

- **Linux + X11** (Wayland is not supported — `mouseferry` relies on `xdotool` and `xrandr`).
- **Python 3.8+**
- **scrcpy** ≥ 2.4 (UHID mouse support)
- **xdotool**, **xrandr**
- **adb** (Android Debug Bridge)
- **python-evdev**
- Your user must be in the **`input`** group to read `/dev/input/*`.

### Installing the dependencies

**Debian / Ubuntu**
```bash
sudo apt install scrcpy xdotool x11-xserver-utils adb python3-evdev
```

**Arch / Manjaro**
```bash
sudo pacman -S scrcpy xdotool xorg-xrandr android-tools python-evdev
```

**Fedora**
```bash
sudo dnf install scrcpy xdotool xrandr android-tools python3-evdev
```

Then add yourself to the `input` group (for the return-sweep detection):
```bash
sudo usermod -aG input "$USER"
# Log out and back in for the group change to take effect.
```

## Installation

```bash
git clone https://github.com/mattabott/mouseferry.git
cd mouseferry

# Drop the script somewhere on your PATH
install -Dm755 mouseferry ~/.local/bin/mouseferry

# Optional: auto-start on login (GNOME/KDE/Xfce)
install -Dm644 mouseferry.desktop ~/.config/autostart/mouseferry.desktop
# Then edit the Exec= line in ~/.config/autostart/mouseferry.desktop
# and replace YOUR_HOME with your real $HOME path.
```

The first run creates `~/.config/mouseferry/config.ini` with the default settings.

## Usage

Plug your Android device in (USB debugging on) and confirm `adb devices` lists it, then:

```bash
mouseferry                  # uses the edge from config.ini
mouseferry --left           # phone/tablet is to the LEFT of the PC
mouseferry --right          # phone/tablet is to the RIGHT of the PC
```

- Move the mouse to the configured edge → it crosses over to Android.
- Sweep the mouse back toward the PC hard enough to cross the sensitivity threshold → you're back on the desktop.

Runtime status is printed on stdout; a rolling log is written to `~/.config/mouseferry/last.log`.

## Configuration

File: `~/.config/mouseferry/config.ini`

```ini
[general]
# Screen edge that triggers the switch to Android: left | right
edge = left

# Pixels from the edge required to trigger the switch
threshold = 2

# Mouse polling interval in ms
poll_ms = 50

# Return sensitivity: how strongly you have to sweep the mouse back toward
# the PC to return control. Higher values = a more decisive gesture is
# required. Typical real-world range: 600-1200 depending on mouse DPI
# (the gesture produces a net REL_X delta in this range over ~300 ms).
return_sensitivity = 800

# Which monitor's edge counts as the trigger. See "Multi-monitor setups" below.
monitor = primary

[scrcpy]
# Android device serial (empty = auto-detect via adb)
serial =

# Extra flags passed to scrcpy (space-separated)
extra_args =
```

Tweak `return_sensitivity` if you find the cursor bounces back by accident (raise it) or if the return feels too stiff (lower it). See [Multi-monitor setups](#multi-monitor-setups) below for the `monitor` key.

## Multi-monitor setups

By default `mouseferry` binds the trigger to the **X11 primary monitor**. In a single-monitor setup that's exactly what you want. In a multi-monitor setup it means the trigger fires from the edge of whichever display `xrandr` reports as `primary`, regardless of where that display sits in your virtual desktop.

If the primary is not the monitor next to your Android device, change the target:

```bash
# See what's connected
mouseferry --list-monitors

# Pick a specific output
mouseferry --right --monitor eDP-1

# Or use a 1-based index from --list-monitors
mouseferry --right --monitor 1

# Or snapshot whichever monitor the cursor is on right now
mouseferry --right --monitor auto-from-cursor
```

You can also set it permanently in `~/.config/mouseferry/config.ini`:

```ini
[general]
monitor = eDP-1
```

Values:

| Value | Meaning |
|---|---|
| `primary` *(default)* | The monitor marked `primary` in `xrandr`. Change it with `xrandr --output <name> --primary`. |
| `auto-from-cursor` | Whichever monitor the cursor is on at startup. Position the mouse on the target monitor, then launch. |
| `<output-name>` | Exact xrandr output name (e.g. `eDP-1`, `HDMI-1`, `DP-2`). Stable across sessions for the same hardware. |
| `<1-based index>` | Index from `mouseferry --list-monitors` (e.g. `1` for the first listed, `2` for the second). Convenient for quick switching when you don't remember the xrandr name. |

The edge check is 2D: the trigger only fires when the cursor is both at the configured edge and inside the target monitor's vertical band. This prevents false positives when the cursor wanders onto a monitor stacked above or below.

**Fallback:** if the monitor name you set is not connected (e.g. you undocked), `mouseferry` prints a warning and falls back to `primary`, then to the first available monitor. It keeps working.

**Hotplug:** the monitor layout is snapshotted at startup. If you plug or unplug a display while `mouseferry` is running, restart it to pick up the change.

## How it works, under the hood

1. A main thread polls `xdotool getmouselocation` every `poll_ms` milliseconds. When the X coordinate sits within `threshold` pixels of the configured edge, a scrcpy subprocess is launched with `--mouse=uhid --no-video --no-audio` and its window is focused via `xdotool windowactivate` — SDL grabs the pointer.
2. A second thread opens the physical mouse node through **evdev** and sums the recent `REL_X` deltas in a sliding `RETURN_WINDOW` (300 ms). When the net movement in the "back to PC" direction exceeds `return_sensitivity`, the return is fired: scrcpy is terminated (removing the UHID device and its phantom cursor), the previously focused window is restored, and the pointer is warped back to a sensible spot on the desktop.
3. A short `CAPTURE_SETTLE` grace period after entry prevents the initial SDL grab from being mistaken for a sweep.

The evdev path is what makes this work at all: once SDL grabs the pointer, X11 stops reporting motion to normal clients like `xdotool`.

## Limitations

- **X11 only.** Wayland has no direct equivalent of `xdotool`/`xrandr` as used here; porting would likely require a compositor-specific protocol (e.g. `wlroots` virtual pointers, KDE KWin, GNOME mutter extensions).
- **USB connection recommended.** Wireless ADB works but adds latency that hurts the "feels like a second screen" experience.
- **One Android device at a time.** Multi-device setups need manual `serial` configuration.

## Troubleshooting

- **`ERROR: no mouse found in /dev/input`** — You are not in the `input` group. Run `sudo usermod -aG input $USER`, log out, log back in.
- **The cursor enters Android but never comes back** — `return_sensitivity` is too high, or your mouse DPI is very low. Halve the value and retest.
- **The cursor bounces to Android by accident** — `return_sensitivity` is too low, or `threshold` is too aggressive. Try `threshold = 1` and raise `return_sensitivity`.
- **scrcpy window doesn't focus** — some tiling WMs intercept focus requests; try a floating rule for windows with title `mouseferry`.

## Contributing

Issues and PRs welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) first and open an issue before large changes so we can agree on scope.

## License

Released under the **[PolyForm Noncommercial License 1.0.0](LICENSE)**.

You can use, modify, and share `mouseferry` for any **non-commercial** purpose (personal use, research, education, hobby projects). Commercial use — including selling, offering as a paid service, or bundling into a commercial product — is not permitted.

## Author

**Matteo Cozza** — [mattabott@gmail.com](mailto:mattabott@gmail.com) · [github.com/mattabott](https://github.com/mattabott)

If this saved you a USB-C cable and a swivel chair, consider dropping a ⭐ on the repo.
