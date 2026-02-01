# Bare-Metal Deployment Fixes Plan

Based on integration testing findings from styrene-node (ASUS Q502LA) and t100ta (ASUS T100TA).

## Summary of Issues Found

### 1. Config Path Confusion (P0 - Critical)

**Problem**: The `config_path_override` setting in core-config.yaml is defined but never used.

**Current behavior**:
1. Lifecycle checks only `~/.reticulum/config` (legacy path)
2. If not found, generates temp config in `/tmp/styrened_rns_*`
3. Ignores `~/.config/reticulum/config` (XDG standard)
4. Ignores `/etc/reticulum/config` (system-wide)
5. Ignores `reticulum.config_path_override` from YAML entirely

**Impact**: Users cannot specify custom RNS config paths. The documented `config_path_override: ~/.reticulum` setting has no effect.

### 2. Limited Interface Startup Logging (P1 - Important)

**Problem**: TCP interface startup success/failure isn't logged with actionable detail.

**Current logging**:
```
Initializing RNS with config: /tmp/styrened_rns_abc123
Network interfaces establishing... (cosmetic outbound packet errors suppressed)
RNS initialized successfully
```

**What's missing**:
- Which specific interfaces started (TCP Server on :4242, TCP Client to 192.168.0.57:4242)
- Interface connection state (connected, connecting, failed)
- Retry behavior for TCP client connections
- Timeout information

### 3. No Config Path Precedence Documentation

**Problem**: Users don't know which config locations are checked and in what order.

---

## Proposed Fixes

### Fix 1: Wire Up config_path_override (P0)

**Files to modify**:
- `src/styrened/services/config.py` - Parse the field from YAML
- `src/styrened/services/lifecycle.py` - Use the override in RNS init

**Changes to `config.py` (load_core_config)**:

```python
# In the "reticulum" section parsing block, add:
if "config_path_override" in ret:
    override = ret["config_path_override"]
    if override and override != "null":
        config.reticulum.config_path_override = Path(override).expanduser()
    else:
        config.reticulum.config_path_override = None
```

**Changes to `lifecycle.py` (_initialize_reticulum)**:

```python
def _initialize_reticulum(self) -> bool:
    """Initialize Reticulum networking with proper config precedence."""
    from styrened.services.reticulum import (
        find_reticulum_config,
        generate_rns_config,
        get_reticulum_config_paths,
    )

    # Config precedence:
    # 1. Explicit override from core-config.yaml
    # 2. Standard RNS paths: /etc/reticulum, ~/.config/reticulum, ~/.reticulum
    # 3. Generate temp config if none found

    override = self.config.reticulum.config_path_override
    existing_config = find_reticulum_config(override=override)

    if existing_config:
        logger.info(f"Using existing RNS config: {existing_config / 'config'}")
        if override and existing_config == override:
            logger.debug(f"Config from override: {override}")
        config_dir = existing_config
        self._rns_config_dir = None  # Don't cleanup existing config
    else:
        # Log what we searched
        searched = [str(override)] if override else []
        searched.extend(str(p) for p in get_reticulum_config_paths())
        logger.info(f"No existing RNS config found (searched: {', '.join(searched)})")
        logger.info("Generating temporary RNS config from core-config.yaml")

        # Generate config
        config_content = generate_rns_config(self.config, client_only=self._client_only)
        config_dir = Path(tempfile.mkdtemp(prefix="styrened_rns_"))
        self._rns_config_dir = config_dir
        (config_dir / "config").write_text(config_content)
        logger.debug(f"Generated config:\n{config_content}")

    # ... rest of initialization
```

### Fix 2: Enhanced Interface Logging (P1)

**Files to modify**:
- `src/styrened/services/rns_service.py` - Add interface enumeration after init
- `src/styrened/services/lifecycle.py` - Log interface summary

**Add to `rns_service.py` after RNS init**:

```python
def _log_interface_status(self) -> None:
    """Log status of all RNS interfaces."""
    if not self._reticulum:
        return

    interfaces = self._reticulum.get_interface_info()
    if not interfaces:
        logger.warning("No RNS interfaces configured")
        return

    logger.info(f"RNS interfaces ({len(interfaces)} configured):")
    for iface in interfaces:
        name = iface.get("name", "Unknown")
        iface_type = iface.get("type", "Unknown")
        status = iface.get("status", "unknown")
        
        # Format interface-specific details
        details = []
        if "target_host" in iface:
            details.append(f"target={iface['target_host']}:{iface.get('target_port', '?')}")
        if "listen_port" in iface:
            details.append(f"listen=:{iface['listen_port']}")
        
        detail_str = f" ({', '.join(details)})" if details else ""
        logger.info(f"  [{status.upper():8}] {name} ({iface_type}){detail_str}")
```

**Note**: Need to verify RNS API for `get_interface_info()` - may need to use internal attributes.

### Fix 3: Add Config Path Documentation

**Add to CLAUDE.md or create dedicated doc**:

```markdown
## RNS Configuration Precedence

styrened searches for RNS configuration in this order:

1. **Explicit override** (core-config.yaml):
   ```yaml
   reticulum:
     config_path_override: /custom/path/to/reticulum
   ```

2. **Standard RNS paths** (checked in order):
   - `/etc/reticulum/config` (system-wide)
   - `~/.config/reticulum/config` (XDG standard)
   - `~/.reticulum/config` (legacy)

3. **Generated config** (if none found):
   - Created in `/tmp/styrened_rns_<random>/`
   - Based on `reticulum.interfaces` settings in core-config.yaml
   - Cleaned up on daemon shutdown

### Recommendation

For bare-metal deployments, create `~/.config/reticulum/config` with your
interface definitions and set:

```yaml
reticulum:
  config_path_override: ~/.config/reticulum
```
```

---

## Additional Improvements

### 4. Startup Diagnostics Command

Add `styrened diagnose` command that reports:
- Config paths searched and which was used
- Interface status (connected/disconnected)
- Identity hashes (operator, LXMF)
- Firewall port check (attempt to bind :4242)

### 5. Config Validation on Load

Validate core-config.yaml `reticulum.interfaces` against the actual RNS config to detect mismatches:
- Warn if core-config specifies interfaces but RNS config is being used
- Log which interfaces are from config vs generated

### 6. Firewall Hint Logging

When TCP server fails to bind, log a helpful message:

```python
except OSError as e:
    if e.errno == 98:  # Address already in use
        logger.error(f"Port {port} already in use. Check for other RNS instances.")
    elif e.errno == 13:  # Permission denied
        logger.error(f"Permission denied for port {port}. May need firewall rule:")
        logger.error(f"  sudo iptables -I INPUT -p tcp --dport {port} -j ACCEPT")
```

---

## Implementation Order

| Phase | Task | Priority | Effort |
|-------|------|----------|--------|
| 1 | Parse `config_path_override` from YAML | P0 | Small |
| 1 | Use override in lifecycle.py | P0 | Medium |
| 1 | Add config precedence logging | P0 | Small |
| 2 | Interface startup status logging | P1 | Medium |
| 2 | Document config precedence | P1 | Small |
| 3 | `styrened diagnose` command | P2 | Large |
| 3 | Config validation warnings | P2 | Medium |

---

## Testing Plan

After implementing fixes:

1. **Test config_path_override**:
   ```bash
   # Set override in core-config.yaml
   echo "reticulum:\n  config_path_override: ~/.config/reticulum" >> ~/.config/styrene/core-config.yaml
   
   # Verify it's used
   styrened -v daemon 2>&1 | grep "Using.*config"
   # Should show: Using existing RNS config: ~/.config/reticulum/config
   ```

2. **Test precedence**:
   - Remove all configs, verify temp is generated
   - Create `~/.config/reticulum/config`, verify it's found
   - Set override to non-existent path, verify fallback

3. **Test interface logging**:
   - Start daemon with TCP server + client configured
   - Verify log shows each interface and status
   - Verify connection failures are logged clearly

---

## Related Files

| File | Changes Needed |
|------|----------------|
| `src/styrened/services/config.py` | Parse `config_path_override` |
| `src/styrened/services/lifecycle.py` | Use override, improve logging |
| `src/styrened/services/rns_service.py` | Interface status logging |
| `src/styrened/services/reticulum.py` | Already has `find_reticulum_config()` |
| `docs/LINUX-TEST-DEPLOYMENT.md` | Add config precedence docs |
