# LXMF Group Discussion Model

## Intent

> Parent: [TUI Comms Workspace Model](tui-comms-workspace.md)
> Spawned from: "How should identity-centric Mail and Comms models represent group chats, shared rooms, and forum-style discussion without collapsing everything into one peer-thread abstraction?"

Styrene should model three distinct conversation scopes: Direct, Group, and Forum. Direct threads remain identity-centric. Private group threads are room-centric, use per-room cryptographic isolation with membership epochs, and follow a Signal-style sender-key architecture adapted to LXMF's asynchronous delivery model. Forum/topic discussion remains topic-centric and is better represented as a Pages-adjacent discussion surface than as a private peer thread.
