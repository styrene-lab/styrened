# TUI Comms Workspace Model

## Intent

> Parent: [TUI Information Architecture Refresh](tui-information-architecture.md)
> Spawned from: "How should the Comms workspace and peer workspace represent text, voice, video, presence, and transport fallback without reintroducing duplicate chat surfaces?"

The TUI should separate asynchronous Mail from synchronous Comms in the primary workspace model. Mail owns inbox-style, store-and-forward correspondence. Comms owns direct/live communication, active sessions, presence, voice/video growth, and bridge-backed transport surfaces. The peer workspace remains the per-peer drill-down and must expose peer-specific communication capabilities without replacing the global Mail and Comms aggregate views.
