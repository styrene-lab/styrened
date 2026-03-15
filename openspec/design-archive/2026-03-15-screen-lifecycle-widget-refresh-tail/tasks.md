# Widget-owned refresh and lane-ownership tail — Design Tasks

## 1. Design exploration

- [x] 1.1 Inventory the persistent-resource widgets that still need lifecycle normalization (`ChatWidget`, `CommsSummaryWidget`, `PageBrowserWidget`, `ForgeLog`)
- [x] 1.2 Decide to prefer explicit per-widget cleanup patterns over a shared widget lifecycle base for the first pass
- [x] 1.3 Keep one-shot helpers such as `MessageBubble` and largely action-driven helpers such as `CommandWidget` out of the first migration pass unless new evidence raises their priority
