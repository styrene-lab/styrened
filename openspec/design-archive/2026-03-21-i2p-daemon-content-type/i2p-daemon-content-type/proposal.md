# Daemon: content-type passthrough and /meta https_url

## Intent

Add content_type field to PageResponse, capture from HTTP headers in fetch_url(), default to text/x-micron for NomadNet. Pass through IPC in handle_query_page. Add https_url to /meta endpoint and CoreConfig. Add https_url field to MeshDevice.
