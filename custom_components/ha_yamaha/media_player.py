"""Support for Yamaha Receivers."""

from __future__ import annotations

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import YamahaCoordinator, YamahaData

_LOGGER = logging.getLogger(__name__)


SUPPORTS = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([YamahaMediaPlayer(hass, coordinator)])


class YamahaMediaPlayer(
    CoordinatorEntity[YamahaCoordinator], MediaPlayerEntity, RestoreEntity
):
    """Representation of a Yamaha device."""

    _attr_has_entity_name = True

    entity_description = MediaPlayerEntityDescription(
        key="render",
        translation_key="render",
        device_class=MediaPlayerDeviceClass.RECEIVER,
    )

    def __init__(self, hass, coordinator: YamahaCoordinator):
        """Initialize the Yamaha Receiver."""
        super().__init__(coordinator)
        self.hass = hass
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_media_player"

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def state(self):
        """Return the state of the device."""
        data = self.coordinator.data
        if data is None:
            return STATE_UNAVAILABLE
        if data.is_on:
            if data.play_status is None:
                return STATE_ON

            if data.play_status.playing:
                return STATE_PLAYING

            return STATE_IDLE

        return STATE_OFF

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        if (data := self.coordinator.data) is None:
            return None
        return data.volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        if (data := self.coordinator.data) is None:
            return None
        return data.muted

    @property
    def source(self):
        """Return the current input source."""
        if (data := self.coordinator.data) is None:
            return None
        return data.current_source

    @property
    def source_list(self):
        """List of available input sources."""
        if (data := self.coordinator.data) is None:
            return None
        return data.source_list

    @property
    def sound_mode(self):
        """Return the current sound mode."""
        if (data := self.coordinator.data) is None:
            return None
        return data.sound_mode

    @property
    def sound_mode_list(self):
        """Return the current sound mode."""
        if (data := self.coordinator.data) is None:
            return None
        return data.sound_mode_list

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        supported_features = SUPPORTS

        data: YamahaData = self.coordinator.data
        if data is None:
            return supported_features

        if data.sound_mode_list:
            supported_features |= MediaPlayerEntityFeature.SELECT_SOUND_MODE

        if data.playback_support is None:
            supports = data.playback_support
            mapping = {
                "play": (
                    MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PLAY_MEDIA
                ),
                "pause": MediaPlayerEntityFeature.PAUSE,
                "stop": MediaPlayerEntityFeature.STOP,
                "skip_f": MediaPlayerEntityFeature.NEXT_TRACK,
                "skip_r": MediaPlayerEntityFeature.PREVIOUS_TRACK,
            }
            for attr, feature in mapping.items():
                if getattr(supports, attr, False):
                    supported_features |= feature

        return supported_features

    async def async_turn_on(self):
        """Turn the media player on."""
        await self.coordinator.async_turn_on()
        # TODO: 设置音量
        await self.coordinator.async_refresh()

    async def async_turn_off(self):
        """Turn off media player."""
        await self.coordinator.async_turn_off()
        await self.coordinator.async_refresh()

    async def async_set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        await self.coordinator.async_set_volume(volume)

    async def async_mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        await self.coordinator.async_mute_volume(mute)

    async def async_media_play(self):
        """Send play command."""
        await self.coordinator.async_play()

    async def async_media_pause(self):
        """Send pause command."""
        await self.coordinator.async_pause()

    async def async_media_stop(self):
        """Send stop command."""
        await self.coordinator.async_stop()

    async def async_media_previous_track(self):
        """Send previous track command."""
        await self.coordinator.async_previous_track()

    async def async_media_next_track(self):
        """Send next track command."""
        await self.coordinator.async_next_track()

    async def async_select_source(self, source):
        """Select input source."""
        await self.coordinator.async_select_source(source)

    async def async_play_media(self, media_type, media_id, **kwargs):
        """Play media from an ID.

        This exposes a pass through for various input sources in the
        Yamaha to direct play certain kinds of media. media_type is
        treated as the input type that we are setting, and media id is
        specific to it.
        For the NET RADIO mediatype the format for ``media_id`` is a
        "path" in your vtuner hierarchy. For instance:
        ``Bookmarks>Internet>Radio Paradise``. The separators are
        ``>`` and the parts of this are navigated by name behind the
        scenes. There is a looping construct built into the yamaha
        library to do this with a fallback timeout if the vtuner
        service is unresponsive.
        NOTE: this might take a while, because the only API interface
        for setting the net radio station emulates button pressing and
        navigating through the net radio menu hierarchy. And each sub
        menu must be fetched by the receiver from the vtuner service.
        """
        if media_type == "NET RADIO":
            await self.coordinator.async_play_media(media_id)

    async def async_select_sound_mode(self, sound_mode):
        """Set Sound Mode for Receiver.."""
        await self.coordinator.async_select_sound_mode(sound_mode)

    @property
    def media_artist(self):
        """Artist of current playing media."""
        data = self.coordinator.data
        if data is not None and data.play_status is not None:
            return self.coordinator.data.play_status.artist

        return None

    @property
    def media_album_name(self):
        """Album of current playing media."""
        data = self.coordinator.data
        if data is not None and data.play_status is not None:
            return self.coordinator.data.play_status.album

        return None

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        # Loose assumption that if playback is supported, we are playing music
        data = self.coordinator.data
        if data is not None and data.playback_support.play:
            return MediaType.MUSIC
        return None

    @property
    def media_title(self):
        """Artist of current playing media."""
        data = self.coordinator.data
        if data is not None and data.play_status is not None:
            song = self.coordinator.data.play_status.song
            station = self.coordinator.data.play_status.station

            # If both song and station is available, print both, otherwise
            # just the one we have.
            if song and station:
                return f"{station}: {song}"

            return song or station
        return None

    @property
    def media_image_url(self) -> str | None:
        """Image url of current playing media."""
        data = self.coordinator.data
        if data is None:
            return None

        album = None
        if data.play_status is not None:
            album = self.coordinator.data.play_status.album

        return album or self.coordinator.device_icon
