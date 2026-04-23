# Contributing to mouseferry

Thanks for considering a contribution! A few quick notes to keep things smooth.

## Before you open a PR

- **Open an issue first** for anything larger than a typo or a one-line fix, so we can agree on scope before you spend time.
- **Keep the scope tight.** `mouseferry` intentionally stays small — it's one script that wraps scrcpy, not a framework. New flags, new config knobs, and new code paths need a clear user-facing justification.
- **Match the existing style.** No external formatter is enforced; just follow what's already there (4-space indent, descriptive names, minimal comments — comment the *why*, not the *what*).

## Running lint locally

```bash
pip install ruff
ruff check mouseferry
```

CI runs the same check on every PR.

## Testing your change

There is no automated test suite — this project drives real hardware. Please describe in the PR:

1. Your environment (distro, desktop/WM, scrcpy version, Android device).
2. What you tested manually: entry, return at different sensitivity values, behaviour when scrcpy fails to start, behaviour when the Android device is disconnected mid-session.

Screenshots or short screen recordings help a lot.

## License of contributions

By submitting a contribution you agree that it will be released under the project's [PolyForm Noncommercial License 1.0.0](LICENSE).
