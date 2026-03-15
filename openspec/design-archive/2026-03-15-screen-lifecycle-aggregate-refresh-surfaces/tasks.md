# Aggregate refresh surfaces lifecycle migration — Design Tasks

## 1. Design exploration

- [x] 1.1 Confirm the remaining standalone screen tail splits into aggregate refresh surfaces versus provisioning-specific workflow ownership.
- [x] 1.2 Audit `InboxScreen`, `ContactsScreen`, and `CommsScreen` for repeated lifecycle responsibilities that now belong in `StyreneScreen`.
- [x] 1.3 Decide whether this slice needs a new helper or should migrate directly onto `StyreneScreen` and screen-local `WidgetResourceScope` ownership.
- [x] 1.4 Define file scope, constraints, and acceptance criteria for the aggregate refresh migration slice.
- [x] 1.5 Record the out-of-scope provisioning follow-up as a separate child node.
