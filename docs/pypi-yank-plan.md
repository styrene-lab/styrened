# PyPI Yank Plan for Legacy Python styrened Safety Remediation

This plan is intentionally staged. Publish the safe release first, then yank known-bad historical releases so existing users have an upgrade target.

## Safe release

Safe release target: `styrened==0.18.0`

Rationale: the working tree already has `VERSION` and `src/styrened/__init__.py` at `0.18.0`, while PyPI currently reports latest public version `0.17.2`. The safety release should publish the current `0.18.0` rather than bumping to an unpublished `0.18.1`.

The release contains:

- one-hour public announce minimum and validation,
- removal of sub-hour TUI announce presets,
- TCP churn re-announce suppression,
- bounded LXMF path-request fanout,
- Meshtastic/MQTT bridge config poison pill,
- Python daemon maintenance policy and README warning.

## Release commands

From the commit containing the safety fixes:

```bash
just check-versions
.venv/bin/ruff check src tests
.venv/bin/pytest tests/unit/test_config_validate.py tests/unit/test_lxmf_service.py tests/tui/services/test_config_persistence.py -q

git tag -a v0.18.0 -m "Release v0.18.0"
git push origin main --tags
```

If publishing manually instead of tag-triggered CI:

```bash
.venv/bin/python -m pip install build twine
rm -rf dist/
.venv/bin/python -m build
.venv/bin/python -m twine upload dist/*
```

## Yank scope

After `0.18.0` is visible on PyPI, yank all previously published `styrened` releases that could be installed instead of the safety release.

Reason text:

```text
Legacy Python styrened safety remediation: upgrade to 0.18.0. Older releases can emit unsafe Reticulum announce/path-request traffic and do not include the Meshtastic/MQTT bridge config poison pill.
```

Recommended yank set from current PyPI inventory:

- `0.17.2`
- `0.17.1`
- `0.16.1`
- `0.16.0`
- `0.15.5`
- `0.15.4`
- `0.15.3`
- `0.15.2`
- `0.15.1`
- `0.15.0`
- all `0.14.*`
- all `0.13.*`
- all `0.12.*`
- all `0.11.*`
- all `0.10.*`
- `0.9.1`
- `0.9.0`
- `0.6.0`

## Yank commands

PyPI yanking requires project owner credentials. Use `pypi` CLI if available:

```bash
python -m pip install pypi-cli
pypi yank styrened 0.17.2 --reason "Legacy Python styrened safety remediation: upgrade to 0.18.0. Older releases can emit unsafe Reticulum announce/path-request traffic and do not include the Meshtastic/MQTT bridge config poison pill."
```

For bulk yanking, generate exact commands from PyPI inventory:

```bash
python -m pip index versions styrened \
  | sed -n 's/^Available versions: //p' \
  | tr ',' '\n' \
  | sed 's/^ *//' \
  | grep -v '^0\.18\.0$' \
  | while read -r version; do
      pypi yank styrened "$version" --reason "Legacy Python styrened safety remediation: upgrade to 0.18.0. Older releases can emit unsafe Reticulum announce/path-request traffic and do not include the Meshtastic/MQTT bridge config poison pill."
    done
```

If using the PyPI web UI instead:

1. Open the `styrened` project release history.
2. Confirm `0.18.0` is published and installable.
3. Yank each older release using the reason above.
4. Do not delete the project; yanking preserves reproducibility for explicit pins while steering normal installs to the safe release.

## Post-yank verification

```bash
python -m pip index versions styrened
python -m venv /tmp/styrened-safe-check
/tmp/styrened-safe-check/bin/python -m pip install --upgrade pip
/tmp/styrened-safe-check/bin/python -m pip install styrened==0.18.0
/tmp/styrened-safe-check/bin/styrened --version
```

Then comment on issue #17 and close it.
