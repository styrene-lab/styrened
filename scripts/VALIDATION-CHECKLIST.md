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
| Hub status shows | GET_HUB_STATUS ✅ | "disabled" (standalone) | ☐ |
| Unread counts load | GET_UNREAD_COUNTS ✅ | Zero counts | ☐ |
| Activity feed populates | GET_ACTIVITY_HISTORY ✅ | Empty list | ☐ |
| No crash on open | — | Screen renders cleanly | ☐ |

### 2. Exploration (Nodes)

IPC calls: `get_devices`, `get_nodes`, `subscribe_devices`, `resolve_name`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Device table renders | QUERY_DEVICES ✅ | Empty table (standalone) | ☐ |
| Nodes table renders | GET_NODES ✅ | Empty table | ☐ |
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
| Core config loads | GET_CORE_CONFIG ✅ | Config dict | ☐ |
| No crash on open | — | Screen renders | ☐ |

### 6. Node Detail Panel

IPC calls: `query_device_status`, `get_path_info`, `datalink_status`, `datalink_meta`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Panel opens for a node | CMD_DEVICE_STATUS ✅ | Timeout (no remote) | ☐ |
| Path info loads | QUERY_PATH_INFO ⚠️ | NotImplemented → graceful | ☐ |

### 7. Pages (I2P Browser)

IPC calls: `fetch_page`, `page_disconnect`, `page_list_sites`, `page_save_site`

| Check | Rust dispatch | Expected | Status |
|-------|--------------|----------|--------|
| Pages screen opens | — | Screen renders | ☐ |
| (All page IPC unimplemented) | ⚠️ | Graceful errors | ☐ |

## Legend

- ✅ = Dispatched in Rust IPC server (30 types)
- ⚠️ = Type exists in Rust wire.rs but NOT dispatched (returns "unimplemented message type")
- ❌ = Not in wire.rs at all

## IPC Dispatch Coverage

### Dispatched (30) — all TUI startup types covered:
PING, QUERY_STATUS, QUERY_IDENTITY, QUERY_DEVICES, QUERY_AUTO_REPLY,
QUERY_CONFIG, CMD_ANNOUNCE, QUERY_CONVERSATIONS, QUERY_MESSAGES,
CMD_SEND_CHAT, CMD_MARK_READ, CMD_DELETE_CONVERSATION, CMD_DELETE_MESSAGE,
QUERY_CONTACTS, QUERY_RESOLVE_NAME, CMD_SET_IDENTITY, CMD_RETRY_MESSAGE,
CMD_SET_AUTO_REPLY, QUERY_SEARCH_MESSAGES, CMD_SET_CONTACT,
CMD_REMOVE_CONTACT, CMD_DEVICE_STATUS, SUB_DEVICES, SUB_MESSAGES,
GET_HUB_STATUS, GET_UNREAD_COUNTS, GET_NODES, GET_CORE_CONFIG,
GET_ACTIVITY_HISTORY, GET_ADAPTER_STATE, SUB_ACTIVITY

### Remaining gaps (not used by TUI startup):
| Type | Used by | Priority |
|------|---------|----------|
| SAVE_CORE_CONFIG (0x4D) | Settings save | LOW |
| QUERY_PAGE (0x1B) | Pages browser | LOW |
| CMD_PAGE_* (0x44-0x49) | Pages management | LOW |
| CMD_DATALINK_* (0x60-0x66) | DirectLink | MEDIUM |
| CMD_TERMINAL_* (0x50-0x53) | Remote terminal | P3 |
| CMD_BLOCK/UNBLOCK_PEER | Peer blocking | LOW |
| CMD_BOUNDARY_SNAPSHOT | Diagnostics | LOW |
