from dataclasses import dataclass
from datetime import timedelta
import logging
from urllib.parse import urljoin, urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_BASE_URL, CONF_INFO_ID, CONF_SSDP_LOCATION, DOMAIN
from .rxv import RXV, PlaybackSupport, PlayStatus
from .types import RXVDeviceInfo
from .utils import get_store

_LOGGER = logging.getLogger(__name__)

MAX_VOLUME = 15.0
MIN_VOLUME = -80.0
VOLUME_RANGE = MAX_VOLUME - MIN_VOLUME


@dataclass
class YamahaData:
    is_on: bool
    muted: bool
    volume: float
    current_source: str
    playback_support: PlaybackSupport
    sound_mode: str
    play_status: PlayStatus


def min_max(value, min=0, max=1):
    if value < min:
        return min
    if value > max:
        return max
    return value


def reverse_mapping(data):
    return {v: k for k, v in data.items()}


class YamahaCoordinator(DataUpdateCoordinator[YamahaData]):
    def __init__(self, hass, config_entry: ConfigEntry):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=2),
        )
        self.hass = hass
        self.entry_id = config_entry.entry_id
        self._base_url = config_entry.data[CONF_BASE_URL]
        self._info_id = config_entry.data[CONF_INFO_ID]
        self._ssdp_location = config_entry.data[CONF_SSDP_LOCATION]
        self._rxv: RXV = None
        self._source_list = None
        self._icon = None

        self._source_names = {}  # from config_entry
        self._source_ignore = []  # from config_entry
        self._mode_names = {
            "Direct": "直通模式",
            "Straight": "直接解码",
            "Hall in Munich": "慕尼黑音乐厅",
            "Hall in Vienna": "维也纳音乐厅",
            "Chamber": "室内乐",
            "Cellar Club": "地下室俱乐部",
            "The Roxy Theatre": "罗克西剧院",
            "The Bottom Line": "底线俱乐部",
            "Sports": "体育节目",
            "Action Game": "动作游戏",
            "Roleplaying Game": "角色扮演游戏",
            "Music Video": "音乐视频",
            "Standard": "标准模式",
            "Spectacle": "大场面模式",
            "Sci-Fi": "科幻电影",
            "Adventure": "冒险电影",
            "Drama": "剧情电影",
            "Mono Movie": "单声道电影",
            "Surround Decoder": "环绕声解码",
            "2ch Stereo": "2声道立体声",
            "5ch Stereo": "5声道立体声",
        }

        self.device_info = DeviceInfo(identifiers={(DOMAIN, self.entry_id)})

    async def async_setup(self):
        store = get_store(self.hass, self._info_id)
        restored = await store.async_load()
        device = RXVDeviceInfo(**restored)
        self._rxv = RXV(self.hass, device, self._base_url)

        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.entry_id)},
            name=device.friendly_name,
            manufacturer=device.manufacturer,
            model=device.model_name,
            serial_number=device.serial_number,
        )

        self._reverse_source_names = reverse_mapping(self._source_names)
        self._source_list = [
            self._source_names.get(source, source)
            for source in self._rxv.get_inputs()
            if source not in self._source_ignore
        ]

        self._reverse_mode_names = reverse_mapping(self._mode_names)
        self._sound_mode_list = [
            self._mode_names.get(mode, mode)
            for mode in self._rxv.get_surround_programs()
        ]

        if self._rxv.icon:
            ssdp = urlparse(self._ssdp_location)
            self._icon = urljoin(f"{ssdp.scheme}://{ssdp.netloc}", self._rxv.icon)

    async def _async_update_data(self):
        try:
            basic_status = await self._rxv.async_get_basic_status()
            is_on = basic_status.on
            muted = basic_status.mute
            volume = min_max((basic_status.volume - MIN_VOLUME) / VOLUME_RANGE, 0, 1)
            current_input = basic_status.input_source
            sound_mode = basic_status.surround_program

            play_status = await self._rxv.async_get_play_status(current_input)
            playback_support = self._rxv.get_playback_support(current_input)

            return YamahaData(
                is_on=is_on,
                muted=muted,
                volume=volume,
                current_source=self._source_names.get(current_input, current_input),
                playback_support=playback_support,
                sound_mode=self._mode_names.get(sound_mode, sound_mode),
                play_status=play_status,
            )
        except Exception as error:
            raise UpdateFailed(error) from error

    @property
    def device_icon(self):
        return self._icon

    @property
    def source_list(self):
        return self._source_list

    @property
    def sound_mode_list(self):
        return self._sound_mode_list

    async def async_turn_on(self):
        await self._rxv.async_turn_on()

    async def async_turn_off(self):
        await self._rxv.async_turn_off()

    async def async_mute_volume(self, mute):
        await self._rxv.async_set_mute(bool(mute))

    async def async_set_volume(self, volume: float):
        receiver_vol = min_max(
            (volume * VOLUME_RANGE + MIN_VOLUME), MIN_VOLUME, MAX_VOLUME
        )
        await self._rxv.async_set_volume(receiver_vol)

    async def async_play(self, media_id):
        await self._rxv.async_set_net_radio(media_id)

    async def async_pause(self):
        await self._rxv.async_pause()

    async def async_stop(self):
        await self._rxv.async_stop()

    async def async_previous_track(self):
        await self._rxv.async_previous()

    async def async_next_track(self):
        await self._rxv.async_next()

    async def async_select_source(self, source):
        source = self._reverse_source_names.get(source, source)
        await self._rxv.async_set_input(source)

    async def async_play_media(self, media_id):
        await self._rxv.async_set_net_radio(media_id)

    # async def async_enable_output(self, port, enabled):
    #     await self._rxv.async_enable_output(port, enabled)

    # async def async_menu_cursor(self, action):
    #     await self._rxv.async_set_menu_cursor(action)

    # async def async_set_scene(self, scene):
    #     await self._rxv.async_set_scene(scene)

    async def async_select_sound_mode(self, sound_mode):
        sound_mode = self._reverse_mode_names.get(sound_mode, sound_mode)
        await self._rxv.async_set_surround_program(sound_mode)
