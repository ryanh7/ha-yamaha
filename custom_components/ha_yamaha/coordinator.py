from dataclasses import dataclass
import logging
from datetime import timedelta
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.const import CONF_HOST
from .rxv import RXV, PlayStatus, PlaybackSupport
from .const import (
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class YamahaData:
    is_on: bool
    muted: bool
    volume: float
    source_list: list
    current_source: str
    playback_support: PlaybackSupport
    sound_mode: str
    sound_mode_list: list
    play_status: PlayStatus


class YamahaCoordinator(DataUpdateCoordinator[YamahaData]):
    def __init__(self, hass, config_entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=2),
        )
        host = config_entry.data[CONF_HOST]
        self._rxv: RXV = RXV(hass, host, entry_id=config_entry.entry_id, timeout=3)

        self.device_info = None
        self.receiver = None
        self._source_list = None

        self._source_names = {}
        self._source_ignore = []

    async def _async_update_data(self): 
        try:
            if self.receiver is None:
                await self._rxv.async_setup()
                receivers = self._rxv.zone_controllers()
                self.receiver: RXV = receivers[0]
                self._zone = self.receiver.zone
                self.device_info = self.receiver.device_info

            basic_status = await self.receiver.async_get_basic_status()
            #is_on = await self.receiver.async_is_on()
            is_on = basic_status.on

            #current_input = await self.receiver.async_get_input()
            current_input = basic_status.input

            play_status = await self.receiver.async_get_play_status(current_input)
            playback_support = await self.receiver.async_get_playback_support(current_input)

            #muted = await self.receiver.async_is_mute()
            muted = basic_status.mute
            #volume = (await self.receiver.async_get_volume() / 100) + 1
            volume = (basic_status.volume / 100) + 1

            if self._source_list is None:
                await self._async_build_source_list()
            
            sound_mode = None
            sound_mode_list = None
            surround_programs = self.receiver.get_surround_programs()
            if surround_programs:
                sound_mode = await self.receiver.async_get_surround_program()
                sound_mode_list = surround_programs

            return YamahaData(
                is_on=is_on,
                muted=muted,
                volume=volume,
                source_list=list(self.receiver.get_inputs().keys()),
                current_source=current_input,
                playback_support=playback_support,
                sound_mode=sound_mode,
                sound_mode_list=sound_mode_list,
                play_status=play_status
            )
        except (ConfigEntryAuthFailed,UpdateFailed) as error:
            raise error
        except Exception as error:
            #_LOGGER.exception(error)
            raise UpdateFailed(error) from error
        
    async def _async_build_source_list(self):
        """Build the source list."""
        self._reverse_mapping = {
            alias: source for source, alias in self._source_names.items()
        }

        self._source_list = sorted(
            self._source_names.get(source, source)
            for source in self.receiver.get_inputs()
            if source not in self._source_ignore
        )

    async def async_turn_on(self):
        if self.receiver:
            await self.receiver.async_turn_on()
    
    async def async_turn_off(self):
        if self.receiver:
            await self.receiver.async_turn_off()
    
    async def async_mute_volume(self, mute):
        if self.receiver:
            await self.receiver.async_set_mute(bool(mute))
    
    async def async_set_volume(self, volume: float):
        if self.receiver:
            receiver_vol = 100 - (volume * 100)
            negative_receiver_vol = -receiver_vol
            await self.receiver.async_set_volume(negative_receiver_vol)
    
    async def async_play(self, media_id):
        if self.receiver:
            await self.receiver.async_set_net_radio(media_id)
    
    async def async_pause(self):
        if self.receiver:
            await self.receiver.async_pause()
    
    async def async_stop(self):
        if self.receiver:
            await self.receiver.async_stop()

    async def async_previous_track(self):
        if self.receiver:
            await self.receiver.async_previous()
    
    async def async_next_track(self):
        if self.receiver:
            await self.receiver.async_next()
    
    async def async_select_source(self, source):
        if self.receiver:
            source = self._reverse_mapping.get(source, source)
            await self.receiver.async_set_input(source)
    
    async def async_play_media(self, media_id):
        if self.receiver:
            await self.receiver.async_set_net_radio(media_id)
    
    async def async_enable_output(self, port, enabled):
        if self.receiver:
            await self.receiver.async_enable_output(port, enabled)
    
    async def async_menu_cursor(self, action):
        if self.receiver:
            await self.receiver.async_set_menu_cursor(action)

    async def async_set_scene(self, scene):
        if self.receiver:
            await self.receiver.async_set_scene(scene)

    async def async_select_sound_mode(self, sound_mode):
        if self.receiver:
            await self.receiver.async_set_surround_program(sound_mode)