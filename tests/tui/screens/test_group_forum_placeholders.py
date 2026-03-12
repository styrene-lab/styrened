"""Tests for group/forum Mail placeholder screens."""
from __future__ import annotations


import pytest
from textual.widgets import Static

from styrened.tui.screens.forum_thread import ForumThreadScreen
from styrened.tui.screens.mail_group_thread import MailGroupThreadScreen
from styrened.ui_state import (
    DeliveryPathClass,
    ForumThreadMeta,
    GroupParticipantRecord,
    GroupThreadFeatureTier,
    GroupThreadMeta,
    GroupThreadPolicy,
    MediaFrictionLevel,
)


class TestMailGroupThreadScreen:
    def test_group_placeholder_initialization(self) -> None:
        screen = MailGroupThreadScreen(
            thread_id="room-alpha",
            display_name="Alpha Room",
            group=GroupThreadMeta(
                room_id="room-alpha",
                room_name="Alpha Room",
                epoch_id="epoch-2",
                member_count=3,
                participants=(
                    GroupParticipantRecord(
                        identity="peer-a",
                        display_name="Peer A",
                        highest_available_interface="tcp",
                        fallback_interfaces=("lxmf",),
                        delivery_path_class=DeliveryPathClass.HIGH,
                    ),
                    GroupParticipantRecord(
                        identity="peer-b",
                        display_name="Peer B",
                        highest_available_interface="lora",
                        delivery_path_class=DeliveryPathClass.CONSTRAINED,
                        media_friction=MediaFrictionLevel.CONFIRM,
                        requires_media_confirmation=True,
                    ),
                ),
                policy=GroupThreadPolicy(
                    feature_tier=GroupThreadFeatureTier.MINIMAL,
                    bounded_retention=True,
                    auto_media_fetch=False,
                    metadata_first_sync=True,
                    background_catchup=False,
                ),
            ),
        )
        assert screen.thread_id == "room-alpha"
        assert screen.display_name == "Alpha Room"
        assert screen.group is not None
        assert screen.group.epoch_id == "epoch-2"
        assert len(screen.group.participants) == 2
        assert screen.group.policy.feature_tier == GroupThreadFeatureTier.MINIMAL

    def test_tier_headline_describes_effective_local_policy(self) -> None:
        screen = MailGroupThreadScreen(
            thread_id="room-alpha",
            display_name="Alpha Room",
            group=GroupThreadMeta(
                room_id="room-alpha",
                policy=GroupThreadPolicy(
                    feature_tier=GroupThreadFeatureTier.MINIMAL,
                    bounded_retention=True,
                    auto_media_fetch=False,
                    metadata_first_sync=True,
                    background_catchup=False,
                ),
            ),
        )

        assert "room continuity is preserved" in screen._tier_headline(screen.group.policy)
        details = screen._tier_details(screen.group.policy)
        assert "History: bounded retention" in details
        assert "Sync: metadata-first" in details
        assert "Media: confirm/fetch on demand" in details
        assert "Catch-up: manual/on-open only" in details

    @pytest.mark.asyncio
    async def test_group_screen_renders_policy_explanation_and_warning(self) -> None:
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        screen = MailGroupThreadScreen(
            thread_id="room-alpha",
            display_name="Alpha Room",
            group=GroupThreadMeta(
                room_id="room-alpha",
                room_name="Alpha Room",
                policy=GroupThreadPolicy(
                    feature_tier=GroupThreadFeatureTier.BALANCED,
                    bounded_retention=True,
                    auto_media_fetch=False,
                    metadata_first_sync=False,
                    background_catchup=True,
                ),
            ),
        )

        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            headline = app.screen.query_one("#mail-group-thread-tier-headline", Static)
            details = app.screen.query_one("#mail-group-thread-policy-details", Static)
            warning = app.screen.query_one("#mail-group-thread-media-warning", Static)

            assert "Balanced tier active" in str(headline.render())
            rendered_details = str(details.render())
            assert "History: bounded retention" in rendered_details
            assert "Media: confirm/fetch on demand" in rendered_details
            assert "Auto-media fetch is disabled" in str(warning.render())

    @pytest.mark.asyncio
    async def test_group_screen_renders_participant_reachability_snapshot(self) -> None:
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        screen = MailGroupThreadScreen(
            thread_id="room-alpha",
            display_name="Alpha Room",
            group=GroupThreadMeta(
                room_id="room-alpha",
                room_name="Alpha Room",
                participants=(
                    GroupParticipantRecord(
                        identity="peer-a",
                        display_name="Peer A",
                        highest_available_interface="tcp",
                        fallback_interfaces=("lxmf",),
                        delivery_path_class=DeliveryPathClass.HIGH,
                    ),
                    GroupParticipantRecord(
                        identity="peer-b",
                        display_name="Peer B",
                        highest_available_interface="lora",
                        fallback_interfaces=("lxmf",),
                        delivery_path_class=DeliveryPathClass.CONSTRAINED,
                        media_friction=MediaFrictionLevel.CONFIRM,
                    ),
                ),
            ),
        )

        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            participants = app.screen.query_one("#mail-group-thread-participants", Static)
            rendered = str(participants.render())
            assert "Peer A: tcp (high)" in rendered
            assert "Peer B: lora (constrained)" in rendered
            assert "fallback=lxmf" in rendered


class TestForumThreadScreen:
    def test_forum_placeholder_initialization(self) -> None:
        screen = ForumThreadScreen(
            thread_id="topic-1",
            display_name="Mesh Planning",
            forum=ForumThreadMeta(topic_id="topic-1", topic_title="Mesh Planning", page_ref="nomad://board/topic-1"),
        )
        assert screen.thread_id == "topic-1"
        assert screen.display_name == "Mesh Planning"
        assert screen.forum is not None
        assert screen.forum.page_ref == "nomad://board/topic-1"

    @pytest.mark.asyncio
    async def test_forum_screen_renders_topic_metadata(self) -> None:
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        screen = ForumThreadScreen(
            thread_id="topic-1",
            display_name="Mesh Planning",
            forum=ForumThreadMeta(topic_id="topic-1", topic_title="Mesh Planning", page_ref="nomad://board/topic-1"),
        )

        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            title = app.screen.query_one("#forum-thread-title", Static)
            topic_id = app.screen.query_one("#forum-thread-topic-id", Static)
            page_ref = app.screen.query_one("#forum-thread-page-ref", Static)
            placeholder = app.screen.query_one("#forum-thread-placeholder", Static)

            assert "Mesh Planning" in str(title.render())
            assert "topic-1" in str(topic_id.render())
            assert "nomad://board/topic-1" in str(page_ref.render())
            assert "future Pages-adjacent destination" in str(placeholder.render())
