---
id: i2p-pages-strategy
title: I2P Content Strategy — Transport vs. Rendering
status: exploring
parent: tui-workspace-completion
tags: [i2p, pages, security, tui, transport]
open_questions: []
---

# I2P Content Strategy — Transport vs. Rendering

## Overview

The Pages tab's `.i2p` URL support has fetch plumbing (I2P HTTP proxy on port 4444) but no HTML rendering — content goes through parse_micron() and produces garbage. Need to decide: do we render HTML in the TUI, delegate to a real browser, or scope I2P to transport-only?

## Research

### I2P eepsite architecture

Eepsites are standard HTTP web servers (nginx, Apache, Caddy, Jetty) tunneled through I2P. The I2P layer handles encryption and anonymity — no TLS needed. Content is full HTML+CSS+JS, no special format. The HTTP proxy (port 4444) forwards `.i2p` requests through garlic-routed tunnels to the server's I2P tunnel endpoint. There is no "I2P page format" — it's whatever the web server serves.

### Current PageBrowserWidget rendering pipeline

All content (NomadNet and external URLs) flows through: `fetch → parse_micron(content) → render_to_rich(elements)`. No HTML detection, no content-type awareness. External URL fetch via `PageBrowserService.fetch_url()` returns raw bytes decoded to string — HTML tags rendered as literal text through the micron parser.

### HTML-in-TUI rendering options

**stdlib html.parser** — ~20 lines, strips tags to plaintext. No layout, no links, no structure. Zero deps.

**html2text** (PyPI) — Converts HTML to Markdown. Preserves headings, links, lists, emphasis. ~1 dep. Output could feed into Rich markup rendering. Security: parses but doesn't execute anything.

**BeautifulSoup + custom walker** — Full DOM access, extract text/links/structure. Heavy dep (bs4 + lxml/html.parser). Overkill for display-only.

**None of these execute JavaScript.** All are text extraction, not rendering. No CSS layout, no box model, no reflow. The result is readable text, not a web page.

Security surface: HTML parsing bugs in any library could theoretically cause issues, but without JS execution or resource loading (images, iframes, external CSS), the attack surface is minimal — equivalent to running `curl | less`.

### Textual Web / textual-serve bridge

**textual-serve** (PyPI `textual-serve`) turns any Textual app into a web app served in the browser. Key APIs:

- `App.open_url(url)` — opens URL in default browser (terminal mode) or delegates to browser tab (textual-serve mode). Already available in Textual 8.1.1.
- When served via textual-serve, link clicks in the TUI are forwarded via websocket to the browser, which opens them natively.
- File downloads work via ephemeral one-time URLs streamed from server to browser.

This means: if styrene-tui is run via `textual-serve`, we could delegate `.i2p` URLs to the user's browser (which would need its own I2P proxy configured). In terminal mode, `App.open_url()` would attempt `webbrowser.open()` which fails for `.i2p` unless the user has a browser with I2P proxy.

**The bridge is for the TUI-as-webapp case, not for rendering HTML inside the TUI.**

### html2text rendering quality assessment

Tested html2text (PyPI, 1 dep, pure Python) against real sites:

**styrene.dev** — 16KB HTML → 4KB markdown. Excellent: headings, emoji, links, emphasis all preserved. Navigation, feature cards, component descriptions all readable. Images show as alt-text placeholders. Would be a great reading experience in a TUI.

**Wikipedia (via REST API for clean content)** — 49KB HTML → clean structured markdown with headings, links, citations. Article body reads naturally. The full page (with nav chrome) is noisy, but Wikipedia's REST API (`/api/rest_v1/page/html/`) gives chrome-free article HTML.

**Key html2text options**: `body_width=0` (let Rich wrap), `ignore_images=True/False`, `protect_links=True`, `unicode_snob=True`, `skip_internal_links=True`. All configurable per-render.

**Rendering pipeline**: html2text → Markdown string → `rich.markdown.Markdown()` → Textual widget. Rich handles headings, emphasis, links (with terminal hyperlinks via OSC 8), lists, code blocks. The result is genuinely readable — better than lynx for structured content.

### A→C→B degradation path architecture

**Rendering decision point** — when `_load_page()` gets content back, the renderer selection should be:

```
1. Is content micron?  →  parse_micron() → render_to_rich()     [B — native]
2. Is content HTML?    →  html2text()    → Rich Markdown()      [C — fallback]
3. Neither?            →  show as plaintext                      [last resort]
```

**Browser delegation** — orthogonal to rendering. Happens BEFORE fetch:
- User presses `o` (open in browser) on any page → `App.open_url(current_url)`
- For `.i2p` URLs in terminal mode: construct `http://localhost:4444/...` proxy URL
- For textual-serve mode: `open_url()` delegates natively

**Content-type detection heuristic** (no server content-type header available from NomadNet):
- If content starts with `<!DOCTYPE` or `<html` → HTML
- If content contains micron markers (`>` heading, `\`` literal, `-=` separator) → micron
- Default: try micron first, if parse produces zero elements → try HTML → plaintext

**Where html2text lives**: Optional dependency via `styrened[web]` or `styrened[tui]` extra. If not installed, HTML content shows a message: "HTML content — press O to open in browser, or install styrened[tui] for text rendering."

### Existing link navigation infrastructure

PageBrowserWidget already has full internal link navigation:

1. Micron renderer emits `[@click="navigate_link('url')"]` Rich markup for links
2. `_PageBody` (Static subclass) handles `action_navigate_link` → posts `_LinkClicked` message  
3. `PageBrowserWidget.on__link_clicked()` resolves relative paths, re-fetches through pipeline
4. History stack supports back navigation (Backspace binding)
5. External mode already does `urljoin` for relative link resolution

**Key insight**: If html2text output is post-processed to convert `[text](url)` markdown links into the same `[@click="navigate_link('url')"]` Rich markup format, ALL internal navigation works for free — same message flow, same re-fetch, same history stack. No new navigation code needed.

This means html2text-rendered pages get clickable links that navigate within the TUI by default. The user never leaves the reader. Browser delegation becomes an explicit escape hatch, not the default link behavior.

### UX model: Reader with browser escape hatch

**Core metaphor**: This is a *reader*, not a browser. Think w3m/lynx, not Firefox. The TUI is the primary viewing surface. Browser delegation is an escape hatch for when text mode isn't enough.

**User sees**:
```
  af1ec9121da534836e6a39b7d261fa65...:/page/index.mu       📄 micron
  ───────────────────────────────────────────────────────────────────
  > Welcome to the Styrene Community Hub
  ...page content with clickable links...
  ───────────────────────────────────────────────────────────────────
  963B in 1.2s                              ← Backspace  R Reload  O Browser  U URL
```

**Status bar left**: size, transfer time, content type indicator (📄 micron / 🌐 HTML / 📝 text)
**Footer bindings**:
- `Backspace` — back in history (existing)
- `R` / `F5` — reload (existing)  
- `U` — enter URL (existing)
- `O` — **new**: open current page in browser (grayed/hidden if headless)
- `S` — save site (existing)

**Link clicks**: Always navigate internally through the pipeline. HTML links re-fetch through same path. Never auto-delegates to browser.

**`O` key behavior**:
- Desktop terminal: `App.open_url()` → system browser opens the URL
- textual-serve: delegates to browser tab via websocket
- Headless SSH: binding hidden or shows "no browser available" notification
- For `.i2p` URLs: constructs `http://localhost:4444/{path}` proxy URL for browser

**Content type indicator in URL bar**: Shows what renderer is active so the user understands why a page looks different from a "real" browser. No ambiguity about what they're seeing.

**Headless detection**: Check `os.environ.get('DISPLAY')` or `os.environ.get('WAYLAND_DISPLAY')` or `os.environ.get('SSH_CONNECTION')`. If no display server and SSH session detected → hide O binding, don't offer browser delegation.

### Identity as the transport binding — what we already have

**The Styrene announce is already a signed multi-transport endpoint manifest.**

A single Styrene node's announce (signed by its RNS identity) includes:
```
styrene:{display_name}:{version}:{caps}:{lxmf_dest}:{short_name}:{sys_fingerprint}:{nomadnet_dest}
```

And the `/meta` DirectLink endpoint returns:
```json
{
  "capabilities": ["lxmf", "rpc", "datalink", "yggdrasil", "i2p", "pages"],
  "ygg_address": "200:abcd::1",
  "ygg_port": 9002,
  "b32_address": "un5a63xeqltbvrdm456fggcxqnwwbio5zzfjhjh3v5bxvaza5saq.b32.i2p"
}
```

**What's already known per node:**
- `identity_hash` — RNS cryptographic identity (the trust anchor)
- `destination_hash` — RNS destination (for LXMF, RPC, chat)
- `nomadnet_destination_hash` — NomadNet page server dest (from announce field 8 or inferred)
- `b32_address` — I2P b32 address (from `/meta` response, stored on MeshDevice)
- `capabilities` list — includes "pages", "i2p", "yggdrasil" flags

**The identity_hash IS the binding.** If a node signs an announce with its RNS identity that says "I have pages capability and my NomadNet dest is X", and then `/meta` (over an authenticated DirectLink from that same identity) says "my b32 is Y" — we know X and Y belong to the same identity. No cross-system crypto proof needed; the trust chain is: RNS identity → signed announce → authenticated DirectLink → /meta response.

**What's NOT in the announce today:**
- HTTPS URL for the node's web presence (e.g. styrene.dev)
- Whether the I2P eepsite serves micron or HTML
- Whether the HTTPS site is the "same content" as the NomadNet pages

The HTTPS URL is the one piece that can't be cryptographically bound — DNS/TLS is a completely separate trust system. But for Styrene-operated nodes, the operator controls all endpoints, so self-declaration is sufficient.

### Transport selector UX model

**When a user selects a node in Pages, the TUI already knows its available transports.** The node's `MeshDevice` has:
- `nomadnet_destination_hash` → NomadNet (micron) transport available
- `b32_address` → I2P transport available (content type unknown until fetched)
- `capabilities` includes "pages" → node serves pages
- An HTTPS URL could be added to `/meta` response

**Transport selector concept:**
```
  🔑 Styrene Community Hub                    [T] NomadNet ▸ I2P ▸ HTTPS
  af1ec912...:/page/index.mu                  📄 micron · 963B · 1.2s
```

User presses `T` to cycle through available transports for this node:
- **NomadNet** (default) → fetches via RNS destination, renders micron natively
- **I2P** → fetches via `http://{b32_address}.b32.i2p/`, renders via html2text (or micron if hub serves micron over I2P)
- **HTTPS** → fetches via declared URL, renders via html2text

The active transport indicator shows which path is in use. The content-type indicator shows what renderer is active. These are independent: NomadNet always produces micron, but I2P could produce either micron or HTML depending on what the server sends.

**What "same site" means operationally:**
All transports are declared by the same RNS identity. The content MAY differ (micron pages vs HTML site vs I2P eepsite), but the trust anchor is the same cryptographic identity. The user trusts the node, and the node declares its endpoints.

This is NOT "verified same content" — it's "same operator, declared endpoints." That's honest and useful.

### I2P vs NomadNet discovery model — fundamental difference

NomadNet is announce-based: nodes broadcast their destination hash + capabilities over the Reticulum mesh. The Pages tab is essentially a filtered announce log — you see nodes because they reached you.

I2P has no equivalent passive discovery. Eepsites are standard HTTP servers tunneled through I2P garlic routing. To browse an eepsite you need the .b32.i2p address from somewhere. Historical I2P has manually-curated directories (stats.i2p, notbob.i2p) and jump services, but nothing like a mesh announce.

Implications for Styrene Pages discovery:
- NomadNet nodes → appear in Pages tab automatically when they announce
- Styrene node I2P eepsite → discoverable only because the Styrene node announced on the mesh; /meta gives b32_address; T key lets you switch to I2P transport for that node
- Generic I2P eepsites (non-Styrene) → invisible to the Pages tab; user must know the address and type it in the U (URL) bar

The Pages tab is therefore NomadNet-native. I2P is a transport option for already-known Styrene nodes, not a parallel discovery mechanism. A future I2P address book or hub-maintained eepsite directory would be needed to make I2P browsable without prior knowledge of addresses — but that's a separate design problem.

## Decisions

### Decision: Three-tier graceful degradation: A (browser) → C (html2text) → B (micron-native)

**Status:** decided
**Rationale:** A. Delegate HTML to real browser via App.open_url() — always preferred when a browser is available. B. Hub serves micron pages over I2P tunnel — native TUI content, no conversion. C. html2text fallback for when browser unavailable (SSH, headless Pi, edge device) — readable text rendering of HTML in TUI. The degradation path: if browser available → open there; if not → render html2text in TUI; if content is micron-native (B) → render directly with existing parser. styrene.dev is the test case: static, text-heavy, no state.

### Decision: Content-type detection lives daemon-side in PageBrowserService

**Status:** decided
**Rationale:** The daemon has the HTTP response headers from I2P/HTTPS fetches — it knows the content-type. Pass it through in the IPC response so the TUI can choose renderer without guessing. NomadNet pages don't have HTTP headers, so micron is the default when content_type is absent.

### Decision: Internal navigation is default; browser delegation is explicit escape hatch via O key

**Status:** decided
**Rationale:** Clicking links in html2text-rendered pages re-fetches through the same pipeline (reader mode). User stays in TUI by default. O key opens current page in system browser — hidden/grayed when headless. This serves both the desktop user (who can escape to a browser when they want) and the headless Pi user (for whom the TUI IS the interface). Post-process html2text markdown links into [@click="navigate_link(...)"] Rich markup to reuse existing micron link navigation infrastructure.

### Decision: Hub micron-over-I2P is a future transport config, not a TUI change

**Status:** decided
**Rationale:** A Styrene Hub can expose its NomadNet page server port via an I2P HTTP Server Tunnel. The TUI doesn't need changes — the daemon's PageBrowserService.fetch_url() already routes .i2p through the proxy, and if the content served is micron, the existing renderer handles it natively. This is a Hub deployment configuration, tracked separately from the TUI rendering work.

### Decision: Identity-hash is the transport binding — same operator, declared endpoints

**Status:** decided
**Rationale:** A Styrene node's RNS identity_hash is the trust anchor. Announce (signed) declares nomadnet_destination_hash and capabilities. DirectLink /meta (authenticated) returns b32_address, ygg_address, and (new) https_url. All endpoints are cryptographically bound to one identity. "Same site" means "same identity" — content may differ across transports (micron vs HTML), and that's expected. No cross-system crypto proof needed.

### Decision: Transport selector via T keybinding cycles NomadNet → I2P → HTTPS for selected node

**Status:** decided
**Rationale:** When a node has multiple declared endpoints, T key cycles through available transports. Each transport triggers a different fetch path: NomadNet via fetch_page(dest_hash), I2P via fetch_url(http://{b32}.b32.i2p/), HTTPS via fetch_url(https://...). Renderer adapts to content-type returned. URL bar shows active transport indicator. Only transports actually declared by the node appear in the cycle.

### Decision: html2text is a hard dependency in styrened[tui] extra

**Status:** decided
**Rationale:** html2text is pure Python, ~1 transitive dep, tiny. Making it optional adds conditional import complexity for marginal benefit — anyone installing [tui] wants the full reader experience. If html2text is absent (someone installed styrened without [tui]), HTML content shows "install styrened[tui] for reader mode" which is already the expected message for the no-TUI case.

### Decision: New html_renderer.py module in tui/widgets/ for HTML→Rich rendering pipeline

**Status:** decided
**Rationale:** micron_parser.py has a clear responsibility (parsing micron format). Adding HTML concerns there muddies it. A new html_renderer.py houses: html2text conversion with tuned options, markdown link → @click Rich markup post-processing, content-type detection heuristic (HTML vs micron vs plaintext). Clean separation of concerns — PageBrowserWidget dispatches to either micron_parser or html_renderer based on content-type.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/page_browser.py` (modified) — Add content_type to PageResponse dataclass. In fetch_url(), capture Content-Type header from HTTP response. In fetch_page() (NomadNet), default content_type to 'text/x-micron'.
- `src/styrened/ipc/handlers.py` (modified) — Pass content_type through in handle_query_page response data dict.
- `src/styrened/tui/widgets/html_renderer.py` (new) — New module: html2text conversion with tuned options, markdown link→@click post-processing, content-type detection heuristic (detect_content_type, render_html_to_rich).
- `src/styrened/tui/widgets/page_browser.py` (modified) — In _load_page(): branch on content_type from IPC response — dispatch to html_renderer for text/html, micron_parser for text/x-micron, plaintext otherwise. Add T keybinding for transport cycling. Add O keybinding for browser delegation. Track available_transports per selected node.
- `src/styrened/rpc/server.py` (modified) — Add https_url field to _gather_meta() response when configured.
- `src/styrened/models/config.py` (modified) — Add https_url field to I2PConfig or a new identity.web_url config section.
- `src/styrened/models/mesh_device.py` (modified) — Add https_url field to MeshDevice (populated from /meta).
- `pyproject.toml` (modified) — Add html2text to [tui] optional dependency extra.

### Constraints

- html2text must be imported lazily in html_renderer.py with graceful ImportError handling
- Content-type heuristic must NOT run when daemon provides explicit content_type — heuristic is fallback only
- Transport selector only shows transports actually declared by the selected node
- O keybinding must detect headless environment and hide/disable itself when no browser available
