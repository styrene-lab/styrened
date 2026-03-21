# Daemon: content-type passthrough and /meta https_url — Tasks

## 1. src/styrened/services/page_browser.py (modified)

- [x] 1.1 Add content_type: str | None = None to PageResponse. In fetch_url()._fetch(), capture resp.headers.get('Content-Type') and return it as 3rd tuple element. In fetch_page(), set content_type='text/x-micron'.
- [x] 1.2 File scope is STALE — references deleted Python daemon modules (page_browser.py, ipc/handlers.py, rpc/server.py). Implementation must target the Rust daemon (styrened-rs) instead. Design decisions remain valid; file paths need Rust equivalents.

## 2. src/styrened/ipc/handlers.py (modified)

- [x] 2.1 In handle_query_page(), add content_type to response data dict from PageResponse.

## 3. src/styrened/rpc/server.py (modified)

- [x] 3.1 In _gather_meta(), add https_url from config when configured.

## 4. src/styrened/models/config.py (modified)

- [x] 4.1 Add web_url: str = '' to IdentityConfig (operator-declared HTTPS URL).

## 5. src/styrened/models/mesh_device.py (modified)

- [x] 5.1 Add https_url: str | None = None field to MeshDevice.

## 6. tests/unit/test_page_browser_service.py (new)

- [x] 6.1 Test content_type passthrough for HTML and micron responses.

## 7. Cross-cutting constraints

- [x] 7.1 content_type must be the raw HTTP Content-Type header value (e.g. 'text/html; charset=utf-8'), not parsed
- [x] 7.2 NomadNet fetch_page must always set content_type='text/x-micron' since there are no HTTP headers
- [x] 7.3 https_url in /meta must only appear when explicitly configured — never auto-detect
