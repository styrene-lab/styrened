# TUI → Rust Daemon Validation Checklist

## How to Run

```bash
# Tests only (automated)
./scripts/validate-rust-daemon.sh

# Tests + manual TUI walkthrough
./scripts/validate-rust-daemon.sh --tui

# TUI only (skip tests)
./scripts/validate-rust-daemon.sh --tui-only
```

## Automated Tests (11 contract + 56 wire compat)

| Test | IPC Type | Status |
|------|----------|--------|
| ping_pong | PING→PONG | ☐ |
| query_status | QUERY_STATUS→RESULT | ☐ |
| query_identity | QUERY_IDENTITY→RESULT | ☐ |
| query_devices | QUERY_DEVICES→RESULT | ☐ |
| query_auto_reply | QUERY_AUTO_REPLY→RESULT | ☐ |
| query_contacts | QUERY_CONTACTS→RESULT | ☐ |
| query_conversations | QUERY_CONVERSATIONS→RESULT | ☐ |
| unknown_type_returns_error | CMD_PQC_STATUS→ERROR | ☐ |
| resolve_name_not_found | QUERY_RESOLVE_NAME→RESULT | ☐ |
| cmd_announce | CMD_ANNOUNCE→RESULT | ☐ |
| concurrent_requests | 5× PING→PONG | ☐ |

## Manual TUI Screens

### 1. Dashboard (Home COP)

IPC calls: `get_status`, `get_devices`, `get_hub_status`, `get_unread_counts`, `subscribe_activity`, `get_activity_history`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Status panel renders | QUERY_STATUS ✅ | Uptime, connected status | ☐ |
| Node count shows | QUERY_DEVICES ✅ | Zero nodes (standalone) | ☐ |
| Hub status shows | GET_HUB_STATUS ⚠️ | "disabled" or similar | ☐ |
| Unread counts load | GET_UNREAD_COUNTS ⚠️ | Zero counts | ☐ |
| Activity feed populates | GET_ACTIVITY_HISTORY ⚠️ | Empty or startup events | ☐ |
| No crash on open | — | Screen renders cleanly | ☐ |

### 2. Exploration (Nodes)

IPC calls: `get_devices`, `get_nodes`, `subscribe_devices`, `resolve_name`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Device table renders | QUERY_DEVICES ✅ | Empty table (standalone) | ☐ |
| Nodes table renders | GET_NODES ⚠️ | Empty table | ☐ |
| No crash on refresh | — | Tables refresh cleanly | ☐ |

### 3. Chat

IPC calls: `get_conversations`, `get_messages`, `send_chat`, `mark_read`, `search_messages`, `subscribe_messages`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Conversation list loads | QUERY_CONVERSATIONS ✅ | Empty list | ☐ |
| Message search works | QUERY_SEARCH_MESSAGES ✅ | Empty results | ☐ |
| No crash opening chat | — | Screen renders | ☐ |

### 4. Contacts

IPC calls: `get_contacts`, `set_contact`, `remove_contact`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Contact list loads | QUERY_CONTACTS ✅ | Empty list | ☐ |
| No crash on open | — | Screen renders | ☐ |

### 5. Settings

IPC calls: `get_config`, `get_core_config`, `get_auto_reply`, `get_identity`, `set_auto_reply`, `set_identity`, `save_core_config`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Config loads | QUERY_CONFIG ✅ | Default config | ☐ |
| Identity loads | QUERY_IDENTITY ✅ | Hash + empty name | ☐ |
| Auto-reply loads | QUERY_AUTO_REPLY ✅ | Disabled state | ☐ |
| Core config loads | GET_CORE_CONFIG ⚠️ | Full config dict | ☐ |
| No crash on open | — | Screen renders | ☐ |

### 6. Node Detail Panel

IPC calls: `query_device_status`, `get_path_info`, `datalink_status`, `datalink_meta`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Panel opens for a node | CMD_DEVICE_STATUS ✅ | Timeout (no remote) | ☐ |
| Path info loads | QUERY_PATH_INFO ❌ | NotImplemented → graceful | ☐ |

### 7. Pages (I2P Browser)

IPC calls: `fetch_page`, `page_disconnect`, `page_list_sites`, `page_save_site`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Pages screen opens | — | Screen renders | ☐ |
| (All page IPC unimplemented) | ⚠️ all | Graceful errors | ☐ |

## Legend

- ✅ = Dispatched in Rust IPC server (17 types)
- ⚠️ = Type exists in Rust wire.rs but NOT dispatched (returns "unimplemented message type")
- ❌ = DaemonFacade returns NotImplemented

## IPC Dispatch Gap Analysis

### Dispatched (17) — should work:
PING, QUERY_STATUS, QUERY_IDENTITY, QUERY_DEVICES, QUERY_AUTO_REPLY,
CMD_ANNOUNCE, QUERY_CONVERSATIONS, QUERY_MESSAGES, CMD_SEND_CHAT,
CMD_MARK_READ, CMD_DELETE_CONVERSATION, CMD_DELETE_MESSAGE,
QUERY_CONTACTS, QUERY_RESOLVE_NAME, CMD_SET_IDENTITY, CMD_RETRY_MESSAGE,
CMD_SET_AUTO_REPLY, QUERY_SEARCH_MESSAGES

### Used by TUI but NOT dispatched — need adding:
| Type | Used by | Priority |
|------|---------|----------|
| GET_HUB_STATUS (0x4E) | Dashboard | HIGH — visible on home |
| GET_UNREAD_COUNTS (0x4F) | Dashboard | HIGH — visible on home |
| GET_NODES (0x1E) | Exploration | HIGH — nodes tab |
| GET_CORE_CONFIG (0x1F) | Settings | MEDIUM |
| GET_ACTIVITY_HISTORY (0x73) | Dashboard | MEDIUM |
| GET_ADAPTER_STATE (0x72) | Dashboard | LOW |
| SAVE_CORE_CONFIG (0x4D) | Settings | LOW |
| QUERY_CONFIG (0x13) | Settings | MEDIUM |
| SUB_DEVICES (0x30) | Exploration | HIGH — live updates |
| SUB_ACTIVITY (0x32) | Dashboard | MEDIUM |
| CMD_DEVICE_STATUS (0x23) | Node detail | MEDIUM |
| QUERY_PAGE (0x1B) | Pages | LOW |
