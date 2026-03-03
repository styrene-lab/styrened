"""Unit tests for parse_announce_data handling of autoreply capability.

Verifies the existing parser correctly handles the autoreply capability
without code changes — this is a locking test.
"""

from styrened.models.mesh_device import parse_announce_data


class TestParseAnnounceAutoReply:
    """Verify parser handles autoreply capability in announce data."""

    def test_parse_announce_with_autoreply_capability(self):
        """Parser should include 'autoreply' in capabilities list."""
        app_data = b"styrene:test-node:0.1.0:hub,api,autoreply:deadbeef:tnode"
        name, dtype, caps, version, lxmf_dest, short_name, _fp, _nn = parse_announce_data(app_data)

        assert name == "test-node"
        assert caps is not None
        assert "autoreply" in caps
        assert "hub" in caps
        assert "api" in caps
        assert short_name == "tnode"

    def test_parse_announce_without_autoreply(self):
        """Parser should not include autoreply when not in data."""
        app_data = b"styrene:test-node:0.1.0:hub,api:deadbeef:tnode"
        name, dtype, caps, version, lxmf_dest, short_name, _fp, _nn = parse_announce_data(app_data)

        assert caps is not None
        assert "autoreply" not in caps

    def test_parse_announce_autoreply_only_capability(self):
        """Parser should handle autoreply as the sole capability."""
        app_data = b"styrene:test-node:0.1.0:autoreply:deadbeef:tnode"
        name, dtype, caps, version, lxmf_dest, short_name, _fp, _nn = parse_announce_data(app_data)

        assert caps == ["autoreply"]
