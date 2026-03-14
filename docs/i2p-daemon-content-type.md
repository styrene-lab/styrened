---
id: i2p-daemon-content-type
title: "Daemon: content-type passthrough and /meta https_url"
status: exploring
parent: i2p-pages-strategy
tags: [daemon, ipc, i2p]
open_questions: []
---

# Daemon: content-type passthrough and /meta https_url

## Overview

Add content_type field to PageResponse, capture from HTTP headers in fetch_url(), default to text/x-micron for NomadNet. Pass through IPC in handle_query_page. Add https_url to /meta endpoint and CoreConfig. Add https_url field to MeshDevice.

## Decisions

### Decision: Implementation complete — content_type on PageResponse, web_url in /meta and config

**Status:** decided
**Rationale:** PageResponse.content_type populated from HTTP Content-Type header in fetch_url(), hardcoded to text/x-micron in fetch_page(). IPC handler passes content_type through. _validate_meta_response now allows ygg_address, ygg_port, b32_address, web_url (was previously stripping them). IdentityConfig.web_url parsed/serialized. _gather_meta includes web_url when configured. MeshDevice.web_url + NodeStore migration. 21 new tests, 3452 total passing.

### Decision: Daemon content-type passthrough implemented

**Status:** decided
**Rationale:** PageResponse.content_type from HTTP headers, IPC passthrough, web_url in config/meta/MeshDevice/NodeStore. _validate_meta_response fixed to allow overlay addresses. 21 tests in test_page_content_type.py all pass.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/page_browser.py` (modified) — Add content_type: str | None = None to PageResponse. In fetch_url()._fetch(), capture resp.headers.get('Content-Type') and return it as 3rd tuple element. In fetch_page(), set content_type='text/x-micron'.
- `src/styrened/ipc/handlers.py` (modified) — In handle_query_page(), add content_type to response data dict from PageResponse.
- `src/styrened/rpc/server.py` (modified) — In _gather_meta(), add https_url from config when configured.
- `src/styrened/models/config.py` (modified) — Add web_url: str = '' to IdentityConfig (operator-declared HTTPS URL).
- `src/styrened/models/mesh_device.py` (modified) — Add https_url: str | None = None field to MeshDevice.
- `tests/unit/test_page_browser_service.py` (new) — Test content_type passthrough for HTML and micron responses.

### Constraints

- content_type must be the raw HTTP Content-Type header value (e.g. 'text/html; charset=utf-8'), not parsed
- NomadNet fetch_page must always set content_type='text/x-micron' since there are no HTTP headers
- https_url in /meta must only appear when explicitly configured — never auto-detect
