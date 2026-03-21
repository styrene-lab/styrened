# TUI Navigation UX — Workspace Consolidation — Design

## Architecture Decisions

### Decision: Unified Exchange workspace with tabbed content

**Status:** decided
**Rationale:** New ExchangeScreen (exchange.py) replaces standalone Mail/Comms/Contacts screens at the top-level navigation layer. TabbedContent with tabs: Mail, Direct, Pages, Contacts. Each tab hosts the content currently in the respective screen. x key opens Exchange. m remains as fast-path that switches to Exchange and focuses the Mail tab. b and c bindings removed. Pages tab lifted from ExplorationScreen — Nodes screen (n) becomes pure network/infrastructure tool.

### Decision: Extract screen content into composable tab widgets

**Status:** decided
**Rationale:** Textual does not support mounting a Screen inside another Screen. Each existing screen's compose/logic is extracted into a standalone Widget subclass (MailTabWidget, DirectTabWidget, PagesTabWidget, ContactsTabWidget). These widgets are mounted into ExchangeScreen's tabs and can also be unit tested independently. Existing standalone screens (inbox.py, comms.py, contacts.py) are kept but deprecated — they delegate to the new widgets to avoid breaking any external consumers.
