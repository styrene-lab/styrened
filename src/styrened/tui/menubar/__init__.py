"""Styrene macOS menu bar agent.

Provides a persistent menu bar icon showing unread message count,
recent conversations, and daemon status. Subscribes to daemon IPC
events for real-time updates.

Requires: pip install styrened[tui] (rumps is included in TUI extras)
Launch:   styrened menubar
"""
