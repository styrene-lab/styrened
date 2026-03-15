# Provision workflow lifecycle ownership

## Intent

> Parent: [Remaining screen-surface lifecycle migration](screen-lifecycle-remaining-screen-surfaces.md)
> Spawned from: "What is the narrowest lifecycle follow-up needed for `ProvisionScreen`'s async mount bootstrap and long-running flash/disk-detect worker ownership?"

Define the narrowest lifecycle follow-up for `ProvisionScreen` now that the aggregate refresh surfaces have been migrated. Unlike Inbox, Contacts, and Comms, Provision owns a staged local workflow — catalog/config bootstrap, disk detection, flash execution, and post-flash mesh watch — so the goal is explicit workflow ownership and teardown rather than blindly mapping the screen onto the generic resume-refresh contract.
