"""Support for Yamaha Receivers."""
from __future__ import annotations

import logging

from dataclasses import dataclass
from typing import Any
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaType,
    MediaPlayerEntityFeature,
    MediaPlayerEntityDescription,
    MediaPlayerDeviceClass
)
from homeassistant.const import (
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.config_entries import ConfigEntry
from .coordinator import YamahaCoordinator
from .rxv import Cursor
from .const import (
    CURSOR_TYPE_DOWN,
    CURSOR_TYPE_LEFT,
    CURSOR_TYPE_RETURN,
    CURSOR_TYPE_RIGHT,
    CURSOR_TYPE_SELECT,
    CURSOR_TYPE_UP,
)

_LOGGER = logging.getLogger(__name__)

ATTR_CURSOR = "cursor"
ATTR_ENABLED = "enabled"
ATTR_PORT = "port"

ATTR_SCENE = "scene"

CONF_SOURCE_IGNORE = "source_ignore"
CONF_SOURCE_NAMES = "source_names"
CONF_ZONE_IGNORE = "zone_ignore"
CONF_ZONE_NAMES = "zone_names"

CURSOR_TYPE_MAP = {
    CURSOR_TYPE_DOWN: Cursor.DOWN,
    CURSOR_TYPE_LEFT: Cursor.LEFT,
    CURSOR_TYPE_RETURN: Cursor.RIGHT,
    CURSOR_TYPE_RIGHT: Cursor.RIGHT,
    CURSOR_TYPE_SELECT: Cursor.SEL,
    CURSOR_TYPE_UP: Cursor.UP,
}
DATA_YAMAHA = "yamaha_known_receivers"
DEFAULT_NAME = "Yamaha Receiver"

STORAGE_KEY = "yamaha"
STORAGE_VERSION = 1

SUPPORTS = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([YamahaMediaPlayer(
        hass, coordinator
    )])

    # added_entities = False

    # @callback
    # def _async_check_entities() -> None:
    #     nonlocal added_entities

    #     if (
    #         not added_entities
    #         #and coordinator.receiver is not None
    #     ):
    #         async_add_entities([YamahaMediaPlayer(
    #             hass, coordinator
    #         )])
    #         added_entities = True

    # coordinator.async_add_listener(_async_check_entities)
    # _async_check_entities()


@dataclass
class YamahaExtraStoredData(ExtraStoredData):
    native_volume: float
    native_muted: bool
    native_source: Any
    native_source_list: Any
    native_sound_mode: Any
    native_sound_mode_list: Any
    native_supported_features: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "native_volume": self.native_volume,
            "native_muted": self.native_muted,
            "native_source": self.native_source,
            "native_source_list": self.native_source_list,
            "native_sound_mode": self.native_sound_mode,
            "native_sound_mode_list": self.native_sound_mode_list,
            "native_supported_features": self.native_supported_features
        }

    @classmethod
    def from_dict(cls, restored: dict[str, Any]) -> YamahaExtraStoredData | None:
        return cls(
            restored.get("native_volume"),
            restored.get("native_muted"),
            restored.get("native_source"),
            restored.get("native_source_list"),
            restored.get("native_sound_mode"),
            restored.get("native_sound_mode_list"),
            restored.get("native_supported_features"),
        )


class YamahaMediaPlayer(CoordinatorEntity[YamahaCoordinator], MediaPlayerEntity, RestoreEntity):
    """Representation of a Yamaha device."""

    entity_description = MediaPlayerEntityDescription(
        key="render",
        translation_key="render",
        device_class=MediaPlayerDeviceClass.RECEIVER,
    )

    def __init__(self, hass, coordinator: YamahaCoordinator, source_ignore=None, source_names=None, zone_names=None):
        """Initialize the Yamaha Receiver."""
        self.hass = hass
        self._source_ignore = source_ignore or []
        self._source_names = source_names or {}
        self._zone_names = zone_names or {}
        self._zone = None
        self._supported_features = None

        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_media_player"
        )

    @property
    def device_info(self):
        return self.coordinator.device_info

    @property
    def extra_restore_state_data(self):
        """Return number specific state data to be restored."""
        return YamahaExtraStoredData(
            self.volume_level,
            self.is_volume_muted,
            self.source,
            self.source_list,
            self.sound_mode,
            self.sound_mode_list,
            self.supported_features,
        )

    async def async_added_to_hass(self) -> None:
        """Restore last state."""
        if ((restored_last_extra_data := await self.async_get_last_extra_data())):
            data = YamahaExtraStoredData.from_dict(
                restored_last_extra_data.as_dict())
            self._volume = data.native_volume
            self._muted = data.native_muted
            self._current_source = data.native_source
            self._source_list = data.native_source_list
            self._sound_mode = data.native_sound_mode
            self._sound_mode_list = data.native_sound_mode_list
            self._supported_features = data.native_supported_features

        await super().async_added_to_hass()


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
        if (data:=self.coordinator.data) is None:
            return None
        return data.volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        if (data:=self.coordinator.data) is None:
            return None
        return data.muted

    @property
    def source(self):
        """Return the current input source."""
        if (data:=self.coordinator.data) is None:
            return None
        return data.current_source

    @property
    def source_list(self):
        """List of available input sources."""
        if (data:=self.coordinator.data) is None:
            return None
        return data.source_list

    @property
    def sound_mode(self):
        """Return the current sound mode."""
        if (data:=self.coordinator.data) is None:
            return None
        return data.sound_mode

    @property
    def sound_mode_list(self):
        """Return the current sound mode."""
        if (data:=self.coordinator.data) is None:
            return None
        return data.sound_mode_list

    @property
    def zone_id(self):
        """Return a zone_id to ensure 1 media player per zone."""
        if self.receiver is None:
            return None
        return f"{self.receiver.ctrl_url}:{self._zone}"

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        data = self.coordinator.data
        if data is None or data.playback_support is None:
            return SUPPORTS

        supported_features = SUPPORTS

        supports = data.playback_support
        mapping = {
            "play": (MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PLAY_MEDIA),
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
        #TODO: 设置音量
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

    async def async_enable_output(self, port, enabled):
        """Enable or disable an output port.."""
        await self.coordinator.async_play_media(port, enabled)

    async def async_menu_cursor(self, cursor):
        """Press a menu cursor button."""
        await self.coordinator.async_menu_cursor(CURSOR_TYPE_MAP[cursor])

    async def async_set_scene(self, scene):
        """Set the current scene."""
        try:
            await self.coordinator.async_set_scene(scene)
        except AssertionError:
            _LOGGER.warning("Scene '%s' does not exist!", scene)
            raise

    async def async_select_sound_mode(self, sound_mode):
        """Set Sound Mode for Receiver.."""
        await self.coordinator.async_select_sound_mode(sound_mode)

    @property
    def media_artist(self):
        """Artist of current playing media."""
        data = self.coordinator.data
        if data is not None and data.play_status is not None:
            self.coordinator.data.play_status.artist
        
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
            return  MediaType.MUSIC
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
