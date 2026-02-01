"""Integration tests for styrened.

Integration tests verify client/server interactions using local RNS.
These tests spawn separate processes and test protocol pathways
without requiring Kubernetes.

Test categories:
- Ping/Pong: Basic connectivity validation
- Status RPC: Status request/response flow
- Exec RPC: Command execution flow
- Chat: Message delivery and acknowledgment
- Announce: Discovery and mesh formation
"""
