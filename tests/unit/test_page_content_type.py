"""Tests for content_type field on PageResponse and IPC passthrough."""
from __future__ import annotations

from styrened.services.page_browser import PageResponse, PageStatus


class TestPageResponseContentType:
    """PageResponse.content_type field."""

    def test_content_type_defaults_to_none(self):
        resp = PageResponse(
            content="hello",
            status=PageStatus.OK,
            destination_hash="abc123",
            path="/page/index.mu",
            transfer_time=0.5,
            content_length=5,
        )
        assert resp.content_type is None

    def test_content_type_set_to_micron(self):
        resp = PageResponse(
            content=">Hello World",
            status=PageStatus.OK,
            destination_hash="abc123",
            path="/page/index.mu",
            transfer_time=0.5,
            content_length=12,
            content_type="text/x-micron",
        )
        assert resp.content_type == "text/x-micron"

    def test_content_type_set_to_html(self):
        resp = PageResponse(
            content="<html><body>hi</body></html>",
            status=PageStatus.OK,
            destination_hash="https://example.com",
            path="/",
            transfer_time=1.0,
            content_length=27,
            content_type="text/html",
        )
        assert resp.content_type == "text/html"

    def test_content_type_preserves_charset_param(self):
        """Raw Content-Type from HTTP headers may include charset."""
        resp = PageResponse(
            content="hello",
            status=PageStatus.OK,
            destination_hash="https://example.com",
            path="/",
            transfer_time=0.5,
            content_length=5,
            content_type="text/html; charset=utf-8",
        )
        assert resp.content_type == "text/html; charset=utf-8"

    def test_error_responses_have_no_content_type(self):
        resp = PageResponse(
            content="",
            status=PageStatus.ERROR,
            destination_hash="abc123",
            path="/page/index.mu",
            transfer_time=0.0,
            content_length=0,
            error_message="Something went wrong",
        )
        assert resp.content_type is None


class TestValidateMetaResponseOverlayFields:
    """_validate_meta_response passes overlay addresses and web_url through."""

    def test_ygg_address_passes_through(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "ygg_address": "200:abcd:ef01::1",
        })
        assert meta is not None
        assert meta["ygg_address"] == "200:abcd:ef01::1"

    def test_ygg_port_passes_through(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "ygg_address": "200:abcd::1",
            "ygg_port": 9002,
        })
        assert meta is not None
        assert meta["ygg_port"] == 9002

    def test_ygg_port_must_be_int(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "ygg_port": "9002",  # string, not int
        })
        assert meta is not None
        assert "ygg_port" not in meta

    def test_b32_address_passes_through(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "b32_address": "un5a63xeqltbvrdm456fggcxqnwwbio5zzfjhjh3v5bxvaza5saq.b32.i2p",
        })
        assert meta is not None
        assert "un5a63x" in meta["b32_address"]

    def test_web_url_passes_through(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "web_url": "https://styrene.dev",
        })
        assert meta is not None
        assert meta["web_url"] == "https://styrene.dev"

    def test_empty_web_url_excluded(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "web_url": "",
        })
        assert meta is not None
        assert "web_url" not in meta

    def test_unknown_fields_still_stripped(self):
        from styrened.services.direct_link import _validate_meta_response

        meta = _validate_meta_response({
            "styrene_version": "0.16.0",
            "hostname": "evil-leak",
            "ip_address": "192.168.1.1",
        })
        assert meta is not None
        assert "hostname" not in meta
        assert "ip_address" not in meta


class TestValidateMetaWebUrlScheme:
    """web_url scheme validation in _validate_meta_response."""

    def _call(self, web_url: str):
        from styrened.services.direct_link import _validate_meta_response
        return _validate_meta_response({"styrene_version": "0.16.0", "web_url": web_url})

    def test_https_url_accepted(self):
        meta = self._call("https://styrene.dev")
        assert meta is not None
        assert meta["web_url"] == "https://styrene.dev"

    def test_http_url_accepted(self):
        meta = self._call("http://my-node.local:8080")
        assert meta is not None
        assert "web_url" in meta

    def test_https_mixed_case_accepted(self):
        meta = self._call("HTTPS://styrene.dev")
        assert meta is not None
        assert "web_url" in meta

    def test_javascript_url_rejected(self):
        meta = self._call("javascript:alert(1)")
        assert meta is not None
        assert "web_url" not in meta

    def test_file_url_rejected(self):
        meta = self._call("file:///etc/passwd")
        assert meta is not None
        assert "web_url" not in meta

    def test_data_url_rejected(self):
        meta = self._call("data:text/html,<script>alert(1)</script>")
        assert meta is not None
        assert "web_url" not in meta

    def test_empty_string_excluded(self):
        meta = self._call("")
        assert meta is not None
        assert "web_url" not in meta


class TestValidateMetaYggPortRange:
    """ygg_port range validation in _validate_meta_response."""

    def _call(self, ygg_port):
        from styrened.services.direct_link import _validate_meta_response
        return _validate_meta_response({"styrene_version": "0.16.0", "ygg_port": ygg_port})

    def test_valid_port_accepted(self):
        meta = self._call(9002)
        assert meta is not None
        assert meta["ygg_port"] == 9002

    def test_port_1_accepted(self):
        meta = self._call(1)
        assert meta is not None
        assert meta["ygg_port"] == 1

    def test_port_65535_accepted(self):
        meta = self._call(65535)
        assert meta is not None
        assert meta["ygg_port"] == 65535

    def test_negative_port_rejected(self):
        meta = self._call(-1)
        assert meta is not None
        assert "ygg_port" not in meta

    def test_port_zero_rejected(self):
        meta = self._call(0)
        assert meta is not None
        assert "ygg_port" not in meta

    def test_port_above_max_rejected(self):
        meta = self._call(99999)
        assert meta is not None
        assert "ygg_port" not in meta

    def test_string_port_rejected(self):
        meta = self._call("9002")
        assert meta is not None
        assert "ygg_port" not in meta


class TestMeshDeviceWebUrl:
    """MeshDevice.web_url field."""

    def test_web_url_defaults_to_none(self):
        from styrened.models.mesh_device import DeviceType, MeshDevice

        device = MeshDevice(
            destination_hash="abc123",
            identity_hash="def456",
            name="Test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0.0,
            announce_count=1,
        )
        assert device.web_url is None

    def test_web_url_can_be_set(self):
        from styrened.models.mesh_device import DeviceType, MeshDevice

        device = MeshDevice(
            destination_hash="abc123",
            identity_hash="def456",
            name="Test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0.0,
            announce_count=1,
            web_url="https://styrene.dev",
        )
        assert device.web_url == "https://styrene.dev"


class TestIdentityConfigWebUrl:
    """IdentityConfig.web_url field."""

    def test_web_url_defaults_to_empty(self):
        from styrened.models.config import IdentityConfig

        config = IdentityConfig()
        assert config.web_url == ""

    def test_web_url_round_trips_through_core_config(self):
        from styrened.models.config import CoreConfig

        config = CoreConfig()
        config.identity.web_url = "https://styrene.dev"
        d = config.to_dict()
        assert d["identity"]["web_url"] == "https://styrene.dev"

    def test_web_url_omitted_when_empty(self):
        from styrened.models.config import CoreConfig

        config = CoreConfig()
        d = config.to_dict()
        assert "web_url" not in d["identity"]

    def test_web_url_parsed_from_yaml(self, tmp_path):
        import yaml

        from styrened.services.config import load_core_config

        config_file = tmp_path / "core-config.yaml"
        config_file.write_text(yaml.dump({
            "identity": {
                "display_name": "Test Node",
                "web_url": "https://styrene.dev",
            }
        }))
        config = load_core_config(config_file)
        assert config.identity.web_url == "https://styrene.dev"


class TestGatherMetaWebUrl:
    """_gather_meta includes web_url when configured."""

    def test_web_url_included_when_configured(self):
        from unittest.mock import MagicMock

        from styrened.rpc.server import RPCServer

        config = MagicMock()
        config.identity.web_url = "https://styrene.dev"
        config.rpc.enabled = False
        config.api.enabled = False
        config.profile.value = "node"

        server = RPCServer.__new__(RPCServer)
        server._ygg_adapter = None
        server._i2p_adapter = None

        meta = server._gather_meta(config)
        assert meta["web_url"] == "https://styrene.dev"

    def test_web_url_omitted_when_empty(self):
        from unittest.mock import MagicMock

        from styrened.rpc.server import RPCServer

        config = MagicMock()
        config.identity.web_url = ""
        config.rpc.enabled = False
        config.api.enabled = False
        config.profile.value = "node"

        server = RPCServer.__new__(RPCServer)
        server._ygg_adapter = None
        server._i2p_adapter = None

        meta = server._gather_meta(config)
        assert "web_url" not in meta

    def test_web_url_omitted_when_no_config(self):
        from styrened.rpc.server import RPCServer

        server = RPCServer.__new__(RPCServer)
        server._ygg_adapter = None
        server._i2p_adapter = None

        meta = server._gather_meta(config=None)
        assert "web_url" not in meta
