# TUI: Transport selector and browser delegation in PageBrowserWidget

## Intent

Wire content-type-aware renderer dispatch in _load_page(). Add T keybinding to cycle available transports (NomadNet/I2P/HTTPS) for the selected node based on declared endpoints. Add O keybinding for browser delegation with headless detection. Add transport/content-type indicators to URL bar and status line.

## Dependencies

- Daemon: content-type passthrough and /meta https_url (implementing)
- TUI: html_renderer module — html2text + link post-processing (implementing)
