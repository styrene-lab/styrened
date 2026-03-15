"""Tests for Exchange screen-content lifecycle coordination."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.lifecycle import ScreenContentHooks, ScreenContentHost
from styrened.tui.screens.exchange import (
    TAB_CONTACTS,
    TAB_DIRECT,
    TAB_MAIL,
    ExchangeScreen,
)
from styrened.tui.services.app_lifecycle import LifecycleMode


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for Exchange lifecycle tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


def _make_mock_lifecycle() -> MagicMock:
    bridge = MagicMock()
    bridge.get_conversations = AsyncMock(return_value=[])
    bridge.get_auto_reply = AsyncMock(return_value={"mode": "disabled"})
    bridge.get_core_config = AsyncMock(return_value={})
    bridge.get_status = AsyncMock(return_value=MagicMock(active_links=0, auto_reply_enabled=False))
    bridge.get_contacts = AsyncMock(return_value=[])

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


def test_screen_content_host_deactivates_previous_slot_before_activating_next() -> None:
    order: list[str] = []
    host = ScreenContentHost(object())
    host.register(
        "mail",
        hooks=ScreenContentHooks(
            activate=lambda initial: order.append(f"mail.activate:{initial}"),
            resume=lambda: order.append("mail.resume"),
            deactivate=lambda: order.append("mail.deactivate"),
        ),
    )
    host.register(
        "direct",
        hooks=ScreenContentHooks(
            activate=lambda initial: order.append(f"direct.activate:{initial}"),
            resume=lambda: order.append("direct.resume"),
            deactivate=lambda: order.append("direct.deactivate"),
        ),
    )

    host.activate("mail")
    host.activate("direct")
    host.activate("mail")

    assert order == [
        "mail.activate:True",
        "mail.deactivate",
        "direct.activate:True",
        "direct.deactivate",
        "mail.resume",
    ]


def test_screen_content_host_cleanup_suspends_active_slot_and_cleans_all() -> None:
    order: list[str] = []
    host = ScreenContentHost(object())
    host.register(
        "mail",
        hooks=ScreenContentHooks(
            activate=lambda initial: order.append(f"mail.activate:{initial}"),
            suspend=lambda: order.append("mail.suspend"),
            cleanup=lambda: order.append("mail.cleanup"),
        ),
    )
    host.register(
        "direct",
        hooks=ScreenContentHooks(cleanup=lambda: order.append("direct.cleanup")),
    )

    host.activate("mail")
    host.cleanup_all()

    assert order == [
        "mail.activate:True",
        "mail.suspend",
        "mail.cleanup",
        "direct.cleanup",
    ]


@pytest.mark.asyncio
async def test_exchange_initial_mail_mount_does_not_eagerly_load_hidden_tabs() -> None:
    lifecycle = _make_mock_lifecycle()
    app = StyreneApp()
    app._lifecycle = lifecycle

    async with app.run_test() as pilot:
        await app.push_screen(ExchangeScreen(initial_tab=TAB_MAIL))
        await pilot.pause()
        await pilot.pause()

        bridge = lifecycle.ipc_bridge
        bridge.get_conversations.assert_awaited()
        bridge.get_auto_reply.assert_awaited()
        bridge.get_core_config.assert_not_called()
        bridge.get_status.assert_not_called()
        bridge.get_contacts.assert_not_called()


@pytest.mark.asyncio
async def test_exchange_tab_switches_trigger_lazy_pane_loads() -> None:
    lifecycle = _make_mock_lifecycle()
    app = StyreneApp()
    app._lifecycle = lifecycle

    async with app.run_test() as pilot:
        await app.push_screen(ExchangeScreen(initial_tab=TAB_MAIL))
        await pilot.pause()
        await pilot.pause()

        bridge = lifecycle.ipc_bridge
        bridge.get_core_config.reset_mock()
        bridge.get_status.reset_mock()
        bridge.get_contacts.reset_mock()

        screen = app.screen
        assert isinstance(screen, ExchangeScreen)

        screen.on_tabbed_content_tab_activated(MagicMock(tab=MagicMock(id=f"tab-{TAB_DIRECT}")))
        await pilot.pause()
        await pilot.pause()

        bridge.get_core_config.assert_awaited()
        bridge.get_status.assert_awaited()
        bridge.get_contacts.assert_not_called()

        bridge.get_contacts.reset_mock()
        screen.on_tabbed_content_tab_activated(MagicMock(tab=MagicMock(id=f"tab-{TAB_CONTACTS}")))
        await pilot.pause()
        await pilot.pause()

        bridge.get_contacts.assert_awaited()


def test_exchange_screen_suspend_and_unmount_delegate_to_content_host() -> None:
    screen = ExchangeScreen()
    host = Mock()
    screen._content_host = host

    screen.on_screen_suspend()
    screen.on_unmount()

    host.suspend_active.assert_called_once_with()
    host.cleanup_all.assert_called_once_with()
