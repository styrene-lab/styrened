# Event Bus Spec

## EventBus subscribe and emit

Given an EventBus instance
When a callback subscribes to "node_changed"
And an event is emitted with type "node_changed", action "announced", dest_hash "abc123"
Then the callback receives the event with type="node_changed", action="announced", dest_hash="abc123"

## Fan-out to multiple subscribers

Given an EventBus with two callbacks subscribed to "node_changed"
When a "node_changed" event is emitted
Then both callbacks are invoked

## Subscriber isolation

Given an EventBus with two callbacks subscribed to "node_changed"
And the first callback raises an exception
When a "node_changed" event is emitted
Then the second callback still receives the event
And the exception is logged, not propagated

## Unsubscribe

Given a callback subscribed to "node_changed"
When the callback is unsubscribed
And a "node_changed" event is emitted
Then the callback is not invoked

## emit does not block caller

Given an EventBus with a slow subscriber (1s sleep)
When emit() is called
Then emit() returns immediately (< 10ms)

## Unsubscribed event types are no-ops

Given an EventBus with no subscribers for "hub_changed"
When a "hub_changed" event is emitted
Then no error occurs

## Daemon wires node_changed on announce

Given a running daemon with EventBus
When an RNS announce is received and processed by the announce handler
Then a "node_changed" event is emitted with action="announced"

## IPC server bridges bus events to activity subscribers

Given an IPC client subscribed to activity events
When the daemon EventBus emits "node_changed"
Then the IPC client receives a CMD_ACTIVITY_EVENT frame with the event data

## TUI receives DaemonEvent via bridge

Given a TUI connected to daemon via IPC bridge
When the daemon emits "node_changed"
Then the TUI app receives a DaemonEvent message with event_type="node_changed"
