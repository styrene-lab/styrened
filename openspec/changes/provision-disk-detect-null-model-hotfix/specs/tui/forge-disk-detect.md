# tui/forge-disk-detect — Delta Spec

## ADDED Requirements

### Requirement: Linux disk detection tolerates nullable model fields

Provisioning disk detection MUST tolerate `lsblk --json` devices whose `model` field is null or empty.

#### Scenario: MMC disk with null model remains selectable
Given `lsblk --json` returns a removable MMC device with `"model": null`
When the Provision screen refreshes disk detection on Linux
Then disk detection completes without raising an exception
And the device is returned with the display name `Unknown`
And the Provision screen worker remains able to populate the disk table

#### Scenario: USB disk with whitespace model uses fallback label
Given `lsblk --json` returns a removable USB device with a model value containing only whitespace
When Linux disk detection parses the entry
Then the device is returned with the display name `Unknown`
And the disk remains included in the results
