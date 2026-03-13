# relay/config

### Requirement: RelayConfig in CoreConfig

CoreConfig gains a relay field with RelayConfig, parsed from YAML.

#### Scenario: Default relay config
Given a CoreConfig with no relay section in YAML
When config is loaded
Then relay is a RelayConfig with defaults (enabled=false)

#### Scenario: Full relay config parsed
Given YAML with relay section: enabled=true, max_sessions=8, max_per_identity=1, idle_timeout=300, allow_permanent=true
When config is loaded
Then relay.enabled is True
And relay.max_sessions is 8
And relay.max_per_identity is 1
And relay.idle_timeout is 300
And relay.allow_permanent is True

#### Scenario: Config serialization round-trip
Given a CoreConfig with relay.enabled=true and max_sessions=32
When serialized to YAML and loaded back
Then relay.enabled is True
And relay.max_sessions is 32

## MODIFIED Requirements

### Requirement: DirectLink tracks link type

DirectLinkService link entries gain a link_type field distinguishing DIRECT from RELAYED.

#### Scenario: Direct link type
Given a DirectLink established via normal path discovery
When the link entry is inspected
Then link_type is LinkType.DIRECT

#### Scenario: Relayed link type
Given a DirectLink established via hub relay
When the link entry is inspected
Then link_type is LinkType.RELAYED
