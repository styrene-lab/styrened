# i2p-review-fixes — Design

## Spec-Derived Architecture

### daemon-validation

- **web_url scheme validated in _validate_meta_response** (modified) — 6 scenarios
- **ygg_port validated to 1-65535 range** (modified) — 4 scenarios
- **ExchangeScreen uses set_mesh_device on fresh browser mount** (added) — 1 scenarios

### html-renderer-security

- **Rich markup in HTML content is escaped before rendering** (added) — 3 scenarios
- **Image markdown syntax is not converted to clickable links** (added) — 3 scenarios
- **Content-type heuristic reduces micron false positives** (modified) — 5 scenarios

### transport-browser

- **.i2p URLs rewritten to localhost proxy for browser delegation** (added) — 3 scenarios
- **Transport cycling performs exactly one fetch** (added) — 2 scenarios
- **O keybinding hidden on headless environments** (added) — 2 scenarios
- **_last_content_kind set on all render paths** (modified) — 2 scenarios

## Scope

<!-- Define what is in scope and out of scope -->

## File Changes

<!-- Add file changes as you design the implementation -->
