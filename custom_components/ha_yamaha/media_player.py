"""Support for Yamaha Receivers."""
from __future__ import annotations

import logging

import requests
import rxv
import voluptuous as vol

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    MEDIA_TYPE_MUSIC,
    SUPPORT_NEXT_TRACK,
    SUPPORT_PAUSE,
    SUPPORT_PLAY,
    SUPPORT_PLAY_MEDIA,
    SUPPORT_PREVIOUS_TRACK,
    SUPPORT_SELECT_SOUND_MODE,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_STOP,
    SUPPORT_TURN_OFF,
    SUPPORT_TURN_ON,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_VOLUME_SET,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.config_entries import ConfigEntry

from .const import (
    CURSOR_TYPE_DOWN,
    CURSOR_TYPE_LEFT,
    CURSOR_TYPE_RETURN,
    CURSOR_TYPE_RIGHT,
    CURSOR_TYPE_SELECT,
    CURSOR_TYPE_UP,
    SERVICE_ENABLE_OUTPUT,
    SERVICE_MENU_CURSOR,
    SERVICE_SELECT_SCENE,
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
    CURSOR_TYPE_DOWN: rxv.RXV.menu_down.__name__,
    CURSOR_TYPE_LEFT: rxv.RXV.menu_left.__name__,
    CURSOR_TYPE_RETURN: rxv.RXV.menu_return.__name__,
    CURSOR_TYPE_RIGHT: rxv.RXV.menu_right.__name__,
    CURSOR_TYPE_SELECT: rxv.RXV.menu_sel.__name__,
    CURSOR_TYPE_UP: rxv.RXV.menu_up.__name__,
}
DATA_YAMAHA = "yamaha_known_receivers"
DEFAULT_NAME = "Yamaha Receiver"

STORAGE_KEY = "yamaha"
STORAGE_VERSION = 1

SUPPORT_YAMAHA = (
    SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_SELECT_SOURCE
    | SUPPORT_PLAY
    | SUPPORT_SELECT_SOUND_MODE
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    config = entry.data
    async_add_entities([YamahaDevice(
        hass, name=config.get(CONF_NAME),  host=config.get(CONF_HOST)
    )])


class YamahaDevice(MediaPlayerEntity):
    """Representation of a Yamaha device."""

    def __init__(self, hass, name, host, source_ignore=None, source_names=None, zone_names=None):
        """Initialize the Yamaha Receiver."""
        self.hass = hass
        self._name = name
        self.host = host
        self.receiver = None
        self._muted = False
        self._volume = 0
        self._pwstate = STATE_UNAVAILABLE
        self._current_source = None
        self._sound_mode = None
        self._sound_mode_list = None
        self._source_list = None
        self._source_ignore = source_ignore or []
        self._source_names = source_names or {}
        self._zone_names = zone_names or {}
        self._reverse_mapping = None
        self._playback_support = None
        self._is_playback_supported = False
        self._play_status = None
        self._zone = None

    def update(self):
        """Get the latest details from the device."""
        try:
            if self.receiver is None:
                ctrl_url = f"http://{self.host}:80/YamahaRemoteControl/ctrl"
                receivers = rxv.RXV(ctrl_url, self._name).zone_controllers()
                self.receiver = receivers[0]
                self._zone = self.receiver.zone
            self._play_status = self.receiver.play_status()
        except requests.exceptions.ConnectionError:
            _LOGGER.info("Receiver is offline: %s", self._name)
            self._pwstate = STATE_UNAVAILABLE
            return
        except Exception:
            self._pwstate = STATE_UNAVAILABLE
            return

        if self.receiver.on:
            if self._play_status is None:
                self._pwstate = STATE_ON
            elif self._play_status.playing:
                self._pwstate = STATE_PLAYING
            else:
                self._pwstate = STATE_IDLE
        else:
            self._pwstate = STATE_OFF

        self._muted = self.receiver.mute
        self._volume = (self.receiver.volume / 100) + 1

        if self.source_list is None:
            self.build_source_list()

        current_source = self.receiver.input
        self._current_source = self._source_names.get(
            current_source, current_source)
        self._playback_support = self.receiver.get_playback_support()
        self._is_playback_supported = self.receiver.is_playback_supported(
            self._current_source
        )
        surround_programs = self.receiver.surround_programs()
        if surround_programs:
            self._sound_mode = self.receiver.surround_program
            self._sound_mode_list = surround_programs
        else:
            self._sound_mode = None
            self._sound_mode_list = None

    def build_source_list(self):
        """Build the source list."""
        self._reverse_mapping = {
            alias: source for source, alias in self._source_names.items()
        }

        self._source_list = sorted(
            self._source_names.get(source, source)
            for source in self.receiver.inputs()
            if source not in self._source_ignore
        )
    
    @property
    def unique_id(self):
        return f"yamaha-{self.host}"

    @property
    def name(self):
        """Return the name of the device."""
        name = self._name
        zone_name = self._zone_names.get(self._zone, self._zone)
        if zone_name and zone_name != "Main_Zone":
            # Zone will be one of Main_Zone, Zone_2, Zone_3
            name += f" {zone_name.replace('_', ' ')}"
        return name

    @property
    def state(self):
        """Return the state of the device."""
        return self._pwstate

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._muted

    @property
    def source(self):
        """Return the current input source."""
        return self._current_source

    @property
    def sound_mode(self):
        """Return the current sound mode."""
        return self._sound_mode

    @property
    def sound_mode_list(self):
        """Return the current sound mode."""
        return self._sound_mode_list

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_list

    @property
    def zone_id(self):
        """Return a zone_id to ensure 1 media player per zone."""
        if self.receiver is None:
            return None
        return f"{self.receiver.ctrl_url}:{self._zone}"

    @property
    def supported_features(self):
        """Flag media player features that are supported."""
        supported_features = SUPPORT_YAMAHA

        supports = self._playback_support
        mapping = {
            "play": (SUPPORT_PLAY | SUPPORT_PLAY_MEDIA),
            "pause": SUPPORT_PAUSE,
            "stop": SUPPORT_STOP,
            "skip_f": SUPPORT_NEXT_TRACK,
            "skip_r": SUPPORT_PREVIOUS_TRACK,
        }
        for attr, feature in mapping.items():
            if getattr(supports, attr, False):
                supported_features |= feature
        return supported_features

    def turn_off(self):
        """Turn off media player."""
        if self.receiver is None:
            return
        self.receiver.on = False

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        if self.receiver is None:
            return
        receiver_vol = 100 - (volume * 100)
        negative_receiver_vol = -receiver_vol
        self.receiver.volume = negative_receiver_vol

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        if self.receiver is None:
            return
        self.receiver.mute = mute

    def turn_on(self):
        """Turn the media player on."""
        if self.receiver is None:
            return
        self.receiver.on = True
        self._volume = (self.receiver.volume / 100) + 1

    def media_play(self):
        """Send play command."""
        if self.receiver is None:
            return
        self._call_playback_function(self.receiver.play, "play")

    def media_pause(self):
        """Send pause command."""
        if self.receiver is None:
            return
        self._call_playback_function(self.receiver.pause, "pause")

    def media_stop(self):
        """Send stop command."""
        if self.receiver is None:
            return
        self._call_playback_function(self.receiver.stop, "stop")

    def media_previous_track(self):
        """Send previous track command."""
        if self.receiver is None:
            return
        self._call_playback_function(self.receiver.previous, "previous track")

    def media_next_track(self):
        """Send next track command."""
        if self.receiver is None:
            return
        self._call_playback_function(self.receiver.next, "next track")

    def _call_playback_function(self, function, function_text):
        try:
            function()
        except rxv.exceptions.ResponseException:
            _LOGGER.warning("Failed to execute %s on %s",
                            function_text, self._name)

    def select_source(self, source):
        """Select input source."""
        if self.receiver is None:
            return
        self.receiver.input = self._reverse_mapping.get(source, source)

    def play_media(self, media_type, media_id, **kwargs):
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
        if self.receiver is None:
            return
        if media_type == "NET RADIO":
            self.receiver.net_radio(media_id)

    def enable_output(self, port, enabled):
        """Enable or disable an output port.."""
        if self.receiver is None:
            return
        self.receiver.enable_output(port, enabled)

    def menu_cursor(self, cursor):
        """Press a menu cursor button."""
        getattr(self.receiver, CURSOR_TYPE_MAP[cursor])()

    def set_scene(self, scene):
        """Set the current scene."""
        if self.receiver is None:
            return
        try:
            self.receiver.scene = scene
        except AssertionError:
            _LOGGER.warning("Scene '%s' does not exist!", scene)

    def select_sound_mode(self, sound_mode):
        """Set Sound Mode for Receiver.."""
        if self.receiver is None:
            return
        self.receiver.surround_program = sound_mode

    @property
    def media_artist(self):
        """Artist of current playing media."""
        if self._play_status is not None:
            return self._play_status.artist

    @property
    def media_album_name(self):
        """Album of current playing media."""
        if self._play_status is not None:
            return self._play_status.album

    @property
    def media_content_type(self):
        """Content type of current playing media."""
        # Loose assumption that if playback is supported, we are playing music
        if self._is_playback_supported:
            return MEDIA_TYPE_MUSIC
        return None

    @property
    def media_title(self):
        """Artist of current playing media."""
        if self._play_status is not None:
            song = self._play_status.song
            station = self._play_status.station

            # If both song and station is available, print both, otherwise
            # just the one we have.
            if song and station:
                return f"{station}: {song}"

            return song or station
