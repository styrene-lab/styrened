# Daemon: content-type passthrough and /meta https_url — Design Spec (extracted)

> Auto-extracted from docs/i2p-daemon-content-type.md at decide-time.

## Decisions

### Implementation complete — content_type on PageResponse, web_url in /meta and config (decided)

PageResponse.content_type populated from HTTP Content-Type header in fetch_url(), hardcoded to text/x-micron in fetch_page(). IPC handler passes content_type through. _validate_meta_response now allows ygg_address, ygg_port, b32_address, web_url (was previously stripping them). IdentityConfig.web_url parsed/serialized. _gather_meta includes web_url when configured. MeshDevice.web_url + NodeStore migration. 21 new tests, 3452 total passing.

### Daemon content-type passthrough implemented (decided)

PageResponse.content_type from HTTP headers, IPC passthrough, web_url in config/meta/MeshDevice/NodeStore. _validate_meta_response fixed to allow overlay addresses. 21 tests in test_page_content_type.py all pass.
