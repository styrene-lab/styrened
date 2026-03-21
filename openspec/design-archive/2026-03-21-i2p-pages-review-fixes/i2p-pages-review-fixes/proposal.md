# I2P pages: adversarial review remediations

## Intent

Fixes for 5 critical issues, 6 warnings, and 5 omissions found during adversarial assessment of the i2p-daemon-content-type, i2p-html-renderer, and i2p-transport-selector implementations. Covers Rich markup injection, image link false matching, .i2p proxy URL construction, double-fetch race, URL scheme validation, micron heuristic false positives, stale content-type indicator, port validation, ExchangeScreen init bypass, and headless binding visibility.

## Dependencies

- TUI: Transport selector and browser delegation in PageBrowserWidget (exploring)
