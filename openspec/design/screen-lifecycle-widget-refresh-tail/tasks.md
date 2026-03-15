# Widget-owned refresh and lane-ownership tail — Design Tasks

## 1. Design exploration

- [x] 1.1 Inventory the persistent-resource widgets that still need lifecycle normalization (`ChatWidget`, `CommsSummaryWidget`, `PageBrowserWidget`, `ForgeLog`)
- [ ] 1.2 Decide whether to use a shared widget-level lifecycle helper or explicit per-widget cleanup patterns
- [x] 1.3 Keep one-shot helpers such as `MessageBubble` and largely action-driven helpers such as `CommandWidget` out of the first migration pass unless new evidence raises their priority
