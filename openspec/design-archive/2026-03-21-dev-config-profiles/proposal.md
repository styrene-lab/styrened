# Dev Config Profiles

## Intent

Named YAML configuration profiles under dev/profiles/ that capture common styrene deployment archetypes. Each profile is a complete core-config.yaml snapshot that can be activated via justfile recipe (e.g. `just dev-daemon profile=full`). Goals: (1) give developers quick access to realistic deployment configs without manual YAML editing, (2) serve as stable fixtures for TUI visual QA sessions, (3) eventually feed into the k8s test suite as parameterized test scenarios against known config shapes.

See [design doc](../../../docs/dev-config-profiles.md).
