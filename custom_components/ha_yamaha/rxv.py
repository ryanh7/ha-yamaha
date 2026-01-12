from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, asdict
import logging
import re
import html
import xml
from collections import namedtuple
from math import floor
from urllib.parse import urljoin

import aiohttp
from defusedxml import cElementTree

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN
from .utils import get_store, get_id_from_udn

from .exceptions import (CommandUnavailable, DescException, MenuUnavailable,
                         MenuActionUnavailable, PlaybackUnavailable,
                         ResponseException, UnknownPort)

_LOGGER = logging.getLogger(__name__)


class PlaybackSupport:
    """Container for Playback support.

    This stores a set of booleans so that they are easy to turn into
    whatever format the support needs to be specified at a higher
    level.

    """
    def __init__(self, play=False, stop=False, pause=False,
                 skip_f=False, skip_r=False):
        self.play = play
        self.stop = stop
        self.pause = pause
        self.skip_f = skip_f
        self.skip_r = skip_r


BasicStatus = namedtuple("BasicStatus", "on volume mute input")
PlayStatus = namedtuple("PlayStatus", "playing artist album song station")
MenuStatus = namedtuple("MenuStatus", "ready layer name current_line max_line current_list")

GetParam = 'GetParam'
YamahaCommand = '<YAMAHA_AV cmd="{command}">{payload}</YAMAHA_AV>'
Zone = '<{zone}>{request_text}</{zone}>'
BasicStatusGet = '<Basic_Status>GetParam</Basic_Status>'
PartyMode = '<System><Party_Mode><Mode>{state}</Mode></Party_Mode></System>'
PowerControl = '<Power_Control><Power>{state}</Power></Power_Control>'
PowerControlSleep = '<Power_Control><Sleep>{sleep_value}</Sleep></Power_Control>'
Input = '<Input><Input_Sel>{input_name}</Input_Sel></Input>'
InputSelItem = '<Input><Input_Sel_Item>{input_name}</Input_Sel_Item></Input>'
ConfigGet = '<{src_name}><Config>GetParam</Config></{src_name}>'
PlayGet = '<{src_name}><Play_Info>GetParam</Play_Info></{src_name}>'
PlayControl = '<{src_name}><Play_Control><Playback>{action}</Playback></Play_Control></{src_name}>'
ListGet = '<{src_name}><List_Info>GetParam</List_Info></{src_name}>'
ListControlJumpLine = '<{src_name}><List_Control><Jump_Line>{lineno}</Jump_Line>' \
                      '</List_Control></{src_name}>'
ListControlCursor = '<{src_name}><List_Control><Cursor>{action}</Cursor>'\
                    '</List_Control></{src_name}>'
CursorControlCursor = '<{src_name}><Cursor_Control><Cursor>{action}</Cursor>'\
                      '</Cursor_Control></{src_name}>'
VolumeLevel = '<Volume><Lvl>{value}</Lvl></Volume>'
VolumeLevelValue = '<Val>{val}</Val><Exp>{exp}</Exp><Unit>{unit}</Unit>'
VolumeMute = '<Volume><Mute>{state}</Mute></Volume>'
SoundVideo = '<Sound_Video>{value}</Sound_Video>'
SelectNetRadioLine = '<NET_RADIO><List_Control><Direct_Sel>Line_{lineno}'\
                     '</Direct_Sel></List_Control></NET_RADIO>'
SelectServerLine = '<SERVER><List_Control><Direct_Sel>Line_{lineno}'\
                   '</Direct_Sel></List_Control></SERVER>'

HdmiOut = '<System><Sound_Video><HDMI><Output><OUT_{port}>{command}</OUT_{port}>'\
          '</Output></HDMI></Sound_Video></System>'
AvailableScenes = '<Config>GetParam</Config>'
Scene = '<Scene><Scene_Sel>{parameter}</Scene_Sel></Scene>'
SurroundProgram = '<Surround><Program_Sel><Current>{parameter}</Current></Program_Sel></Surround>'
DirectMode = '<Sound_Video><Direct>{parameter}</Direct></Sound_Video>'

# inputs constants
INPUT_NET_RADIO = "NET RADIO"
INPUT_SERVER = "SERVER"

# String constants
STRAIGHT = "Straight"
DIRECT = "Direct"

# PlayStatus options
ARTIST_OPTIONS = ["Artist", "Program_Type"]
ALBUM_OPTIONS = ["Album", "Radio_Text_A"]
SONG_OPTIONS = ["Song", "Track", "Radio_Text_B"]
STATION_OPTIONS = ["Station", "Program_Service"]

# Cursor commands.
class Cursor:
    DISPLAY = "Display"
    DOWN = "Down"
    LEFT = "Left"
    MENU = "Menu"
    ON_SCREEN = "On Screen"
    OPTION = "Option"
    SEL = "Sel"
    RETURN = "Return"
    RETURN_TO_HOME = "Return to Home"
    RIGHT = "Right"
    TOP_MENU = "Top Menu"
    UP = "Up"

URL_BASE_QUERY = '*/{urn:schemas-yamaha-com:device-1-0}X_URLBase'
CONTROL_URL_QUERY = '***/{urn:schemas-yamaha-com:device-1-0}X_controlURL'
UNITDESC_URL_QUERY = '***/{urn:schemas-yamaha-com:device-1-0}X_unitDescURL'
UDN_QUERY = (
    "{urn:schemas-upnp-org:device-1-0}device"
    "/{urn:schemas-upnp-org:device-1-0}UDN"
)
MANUFACTURER_QUERY = (
    "{urn:schemas-upnp-org:device-1-0}device"
    "/{urn:schemas-upnp-org:device-1-0}manufacturer"
)
MODEL_NAME_QUERY = (
    "{urn:schemas-upnp-org:device-1-0}device"
    "/{urn:schemas-upnp-org:device-1-0}modelName"
)
FRIENDLY_NAME_QUERY = (
    "{urn:schemas-upnp-org:device-1-0}device"
    "/{urn:schemas-upnp-org:device-1-0}friendlyName"
)
SERIAL_NUMBER_QUERY = (
    "{urn:schemas-upnp-org:device-1-0}device"
    "/{urn:schemas-upnp-org:device-1-0}serialNumber"
)
LIST_ICON_QUERY = (
    "{urn:schemas-upnp-org:device-1-0}device"
    "/{urn:schemas-upnp-org:device-1-0}iconList"
    "/{urn:schemas-upnp-org:device-1-0}icon"
)

@dataclass
class RXVDeviceinfo:
    device_id: str
    friendly_name: str
    manufacturer: str
    model_name: str
    serial_number: str
    icons: list[str]
    zones: list[str]
    commands: list[str]
    zone_surround_programs: dict[str, list[str]]
    source_play_methods: dict[str, list[str]]
    source_cursor_actions: dict[str, list[str]]
    inputs_source: dict[str, str]
    scenes_number: dict[str, str]


class RXV(object):

    def __init__(self, hass, host:str,
                 entry_id: str = None,
                 zone="Main_Zone",
                 timeout=10.0):
        self.hass = hass
        self.host = host
        self.entry_id = entry_id
        self.deivce_desc_url = f'http://{host}:8080/MediaRenderer/desc.xml'
        self.ctrl_url = f'http://{host}:80/YamahaRemoteControl/ctrl'
        self.unit_desc_url = f'http://{host}:80/YamahaRemoteControl/desc.xml'
        self._store = None
        self._session: aiohttp.ClientSession = async_get_clientsession(hass)
        self._http_timeout = aiohttp.ClientTimeout(timeout)

        self._zone = zone

        self._device: RXVDeviceinfo | None = None

        self.icon_list = []

    @property
    def device_info(self):
        if self.entry_id is None:
            return None

        if self._device is None:
            return DeviceInfo(
                identifiers={(DOMAIN, self.entry_id)}
            )

        return DeviceInfo(
            identifiers={(DOMAIN, self.entry_id)},
            name=self._device.friendly_name,
            manufacturer=self._device.manufacturer,
            model=self._device.model_name,
            serial_number=self._device.serial_number
        )
    
    @property
    def device_id(self):
        return self._device.device_id if self._device else None
    
    @property
    def friendly_name(self):
        return self._device.friendly_name if self._device else None
    
    @property
    def serial_number(self):
        return self._device.serial_number if self._device else None
    
    @property
    def icon(self):
        return urljoin(f"http://{self.host}:8080", self._device.icons[0]) if self._device and self._device.icons else None
    
    async def async_setup(self):
        if self._store is None and self.entry_id is not None:
            self._store = get_store(self.hass, self.entry_id)
            restored = await self._store.async_load()
            if restored:
                self._device = RXVDeviceinfo(**restored)
        
        if self._device is None:
            self._device = await self._async_discover_device_info()
            if self._store is not None:
                await self._store.async_save(asdict(self._device))

    async def _async_discover_device_info(self) -> RXVDeviceinfo:
        # 获取设备xml
        response = await self._session.get(
            self.deivce_desc_url, timeout=self._http_timeout
        )
        device_desc_xml = await response.text()
        if not device_desc_xml:
            raise DescException("no device desc xml")
        
        device_desc_xml = cElementTree.fromstring(device_desc_xml)
        #TODO: 设备id不一致的时候发出告警
        udn = device_desc_xml.find(UDN_QUERY).text
        device_id = get_id_from_udn(udn)
        manufacturer = device_desc_xml.find(MANUFACTURER_QUERY).text
        model_name = device_desc_xml.find(MODEL_NAME_QUERY).text
        friendly_name = device_desc_xml.find(FRIENDLY_NAME_QUERY).text
        serial_number = device_desc_xml.find(SERIAL_NUMBER_QUERY).text

        icons = self._build_icon_list(device_desc_xml)

        # 获取控制描述xml
        response = await self._session.get(
            self.unit_desc_url, timeout=self._http_timeout
        )
        unit_desc_xml = await response.text()
        if not unit_desc_xml:
            raise DescException("no desc.xml")

        unit_desc_xml = cElementTree.fromstring(unit_desc_xml)

        zones = self._build_zones(unit_desc_xml)
        commands = self._build_commands(unit_desc_xml)
        zone_surround_programs = self._build_surround_programs(unit_desc_xml)
        source_play_methods = self._build_play_methods(unit_desc_xml)
        source_cursor_actions = self._build_supported_cursor_actions(unit_desc_xml)

        inputs = await self._async_get_inputs()

        scenes = await self._async_get_scenes()

        return RXVDeviceinfo(
            device_id=device_id,
            friendly_name=friendly_name,
            manufacturer=manufacturer,
            model_name=model_name,
            serial_number=serial_number,
            icons=icons,
            zones=zones,
            commands=commands,
            zone_surround_programs=zone_surround_programs,
            source_play_methods=source_play_methods,
            source_cursor_actions=source_cursor_actions,
            inputs_source=inputs,
            scenes_number=scenes
        )

    def _build_icon_list(self, desc_xml):
        icons = [icon for icon in desc_xml.findall(LIST_ICON_QUERY)]
        icon_data = []
        for icon in icons:
            width_elem = icon.find('.//{urn:schemas-upnp-org:device-1-0}width')
            url_elem = icon.find('.//{urn:schemas-upnp-org:device-1-0}url')
            
            if url_elem is not None:
                width = 0
                if width_elem is not None:
                    try:
                        width = int(width_elem.text)
                    except (ValueError, AttributeError):
                        pass
                
                url = url_elem.text
                icon_data.append((width, url))

        icon_data.sort(key=lambda x: x[0], reverse=True)

        return [url for _, url in icon_data]

    def _build_commands(self, desc_xml):
        return [item.text.split(",") for cmd in desc_xml.findall('.//Cmd_List/Define') for item in cmd]

    def _build_zones(self, desc_xml):
        return [
            e.get("YNC_Tag") for e in desc_xml.findall('.//*[@Func="Subunit"]')
        ]

    def _build_play_methods(self, desc_xml):
        source_play_methods = {}
        
        # 查找所有具有YNC_Tag属性的元素
        for source_elem in desc_xml.findall('.//*[@YNC_Tag]'):
            source = source_elem.get('YNC_Tag')
            if not source:
                continue

            play_control = source_elem.find('.//*[@Func="Play_Control"]')
            if play_control is None:
                continue
                
            # 收集所有Put_1的文本内容作为支持的方法
            methods = [s.text for s in play_control.findall('.//Put_1') if s.text]
            if len(methods) == 0:
                continue

            source_play_methods[source] = methods

        return source_play_methods
    
    def _build_supported_cursor_actions(self, desc_xml):
        source_cursor_actions = {}
        
        # 查找所有具有YNC_Tag属性的元素
        for source_elem in desc_xml.findall('.//*[@YNC_Tag]'):
            source = source_elem.get('YNC_Tag')
            if not source:
                continue

            cursor = source_elem.find('.//Menu[@Func="Cursor"]')
            if cursor is None:
                continue
                
            # 收集所有Put_1的文本内容作为支持的方法
            actions = [s.text for s in cursor.findall('.//Put_1') if s.text]
            if len(actions) == 0:
                continue

            source_cursor_actions[source] = actions
        
        return source_cursor_actions
    
    def _build_surround_programs(self, desc_xml):
        zone_surround_programs = {}

        for source_xml in desc_xml.findall('.//*[@Func="Subunit"]'):
            zone = source_xml.get('YNC_Tag')
            if not zone:
                continue

            setup = source_xml.find('.//Menu[@Title_1="Setup"]')
            if setup is None:
                continue

            surround_programs = []
            
            straight = setup.find('.//*[@Title_1="Straight"]/Put_1')
            if straight is not None:
                surround_programs.append(STRAIGHT)

            direct = setup.find('.//*[@Title_1="Direct"]/Put_1')
            if direct is not None:
                surround_programs.append(DIRECT)

            programs = setup.find('.//*[@Title_1="Program"]/Put_2/Param_1')
            if programs is not None:
                supports = programs.findall('.//Direct')
                for s in supports:
                    surround_programs.append(s.text)
            
            zone_surround_programs[zone] = surround_programs
        
        return zone_surround_programs
    
    async def _async_get_inputs(self):
        request_text = InputSelItem.format(input_name=GetParam)
        res = await self._async_request('GET', request_text)
        inputs = dict(zip((elt.text
                                        for elt in res.iter('Param')),
                                        (elt.text
                                        for elt in res.iter("Src_Name"))))
        return inputs
    
    async def _async_get_scenes(self):
        scenes = {}
        res = await self._async_request('GET', AvailableScenes)
        scenes_xml = res.find('.//Scene')
        if scenes_xml is None:
            return scenes

        for scene in scenes_xml:
            scenes[scene.text] = scene.tag.replace("_", " ")

        return scenes
    
    def get_inputs(self):
        return self._device.inputs_source
    
    async def _async_request(self, command, request_text, zone_cmd=True):
        if zone_cmd:
            payload = Zone.format(request_text=request_text, zone=self._zone)
        else:
            payload = request_text

        request_text = YamahaCommand.format(command=command, payload=payload)
        try:
            res = await self._session.post(
                self.ctrl_url,
                data=request_text,
                headers={"Content-Type": "text/xml"},
                timeout=self._http_timeout
            )
            # releases connection to the pool
            response = cElementTree.XML(await res.text())
            if response.get("RC") != "0":
                _LOGGER.error("Request %s failed with %s",
                             request_text, res.content)
                raise ResponseException(res.content)
            return response
        except xml.etree.ElementTree.ParseError:
            _LOGGER.exception("Invalid XML returned for request %s: %s",
                             request_text, res.content)
            raise

    async def async_get_basic_status(self):
        response = await self._async_request('GET', BasicStatusGet)
        on = response.find("%s/Basic_Status/Power_Control/Power" % self.zone).text == "On"
        inp = response.find("%s/Basic_Status/Input/Input_Sel" % self.zone).text
        mute = response.find("%s/Basic_Status/Volume/Mute" % self.zone).text == "On"
        volume = response.find("%s/Basic_Status/Volume/Lvl/Val" % self.zone).text
        volume = int(volume) / 10.0

        status = BasicStatus(on, volume, mute, inp)
        return status

    async def async_is_on(self) -> bool:
        request_text = PowerControl.format(state=GetParam)
        response = await self._async_request('GET', request_text)
        power = response.find("%s/Power_Control/Power" % self._zone).text
        assert power in ["On", "Standby"]
        return power == "On"

    async def async_turn_on_off(self, state):
        assert state in [True, False]
        new_state = "On" if state else "Standby"
        request_text = PowerControl.format(state=new_state)
        response = await self._async_request('PUT', request_text)
        return response

    async def async_turn_on(self):
        return await self.async_turn_on_off(True)
    
    async def async_turn_off(self):
        return await self.async_turn_on_off(False)

    async def async_get_playback_support(self, input_source=None):
        """Get playback support as bit vector.

        In order to expose features correctly in Home Assistant, we
        need to make it possible to understand what play operations a
        source supports. This builds us a Home Assistant compatible
        bit vector from the desc.xml for the specified source.
        """

        src_name = await self._async_get_src_name(input_source)

        return PlaybackSupport(
            play=self.supports_play_method(src_name, 'Play'),
            pause=self.supports_play_method(src_name, 'Pause'),
            stop=self.supports_play_method(src_name, 'Stop'),
            skip_f=self.supports_play_method(src_name, 'Skip Fwd'),
            skip_r=self.supports_play_method(src_name, 'Skip Rev'))

    async def async_is_playback_supported(self, input_source=None):
        support = await self.async_get_playback_support(input_source)
        return support.play

    async def async_play(self):
        await self._async_playback_control('Play')

    async def async_pause(self):
        await self._async_playback_control('Pause')

    async def async_stop(self):
        await self._async_playback_control('Stop')

    async def async_next(self):
        await self._async_playback_control('Skip Fwd')

    async def async_previous(self):
        await self._async_playback_control('Skip Rev')

    async def _async_playback_control(self, action):
        src_name, input_source = await self._async_get_src_name()
        if not src_name:
            return None
        
        if not await self.async_is_playback_supported(input_source):
            raise PlaybackUnavailable(input_source, action)

        request_text = PlayControl.format(src_name=src_name, action=action)
        response = await self._async_request('PUT', request_text, zone_cmd=False)
        return response

    async def async_get_input(self):
        request_text = Input.format(input_name=GetParam)
        response = await self._async_request('GET', request_text)
        return response.find("%s/Input/Input_Sel" % self.zone).text

    async def async_set_input(self, input_name):
        assert input_name in self._device.inputs_source
        request_text = Input.format(input_name=input_name)
        await self._async_request('PUT', request_text)

    async def async_get_outputs(self):
        outputs = {}

        for cmd in self._find_commands('System,Sound_Video,HDMI,Output'):
            # An output typically looks like this:
            #   System,Sound_Video,HDMI,Output,OUT_1
            # Extract the index number at the end as it is needed when
            # requesting its current state.
            m = re.match(r'.*_(\d+)$', cmd)
            if m is None:
                continue

            port_number = m.group(1)
            request = HdmiOut.format(port=port_number, command='GetParam')
            response = await self._async_request('GET', request, zone_cmd=False)
            port_state = response.find(cmd.replace(',', '/')).text.lower()
            outputs['hdmi' + str(port_number)] = port_state

        return outputs

    async def async_enable_output(self, port, enabled):
        m = re.match(r'hdmi(\d+)', port.lower())
        if m is None:
            raise UnknownPort(port)

        request = HdmiOut.format(port=m.group(1),
                                 command='On' if enabled else 'Off')
        await self._async_request('PUT', request, zone_cmd=False)

    def _find_commands(self, cmd_name):
        for cmd in self._device.commands:
            if cmd.startswith(cmd_name):
                yield cmd

    async def async_get_direct_mode(self):
        """
        Current state of direct mode.
        """
        if DIRECT not in self._device.zone_surround_programs.get(self.zone, []):
            return False

        request_text = DirectMode.format(parameter="<Mode>GetParam</Mode>")
        response = await self._async_request('GET', request_text)
        direct = response.find(
            "%s/Sound_Video/Direct/Mode" % self.zone
        ).text == "On"

        return direct

    async def async_set_direct_mode(self, on):
        """
        Enable/Disable direct mode.

        Precondition: DIRECT mode is supported, raises AssertionError otherwise.
        """
        assert DIRECT in self._device.zone_surround_programs.get(self.zone, [])
        if on:
            request_text = DirectMode.format(parameter="<Mode>On</Mode>")
        else:
            request_text = DirectMode.format(parameter="<Mode>Off</Mode>")
        await self._async_request('PUT', request_text)

    def get_surround_programs(self):
        return self._device.zone_surround_programs.get(self.zone)

    async def async_get_surround_program(self):
        """
        Get current selected surround program.

        If a STRAIGHT or DIRECT mode is supported and active, returns that mode.
        Otherwise returns the currently active surround program.
        """
        if await self.async_get_direct_mode():
            return DIRECT

        request_text = SurroundProgram.format(parameter=GetParam)
        response = await self._async_request('GET', request_text)
        straight = response.find(
            "%s/Surround/Program_Sel/Current/Straight" % self.zone
        ).text == "On"

        if straight:
            return STRAIGHT

        program = response.find(
            "%s/Surround/Program_Sel/Current/Sound_Program" % self.zone
        ).text

        return program

    async def async_set_surround_program(self, surround_name):
        assert surround_name in self._device.zone_surround_programs.get(self.zone, [])

        # short circut on direct program
        if surround_name == DIRECT:
            await self.async_set_direct_mode(True)
            return

        if await self.async_get_direct_mode():
            # Disable direct mode before changing any other settings,
            # otherwise they don't have an effect
            await self.async_set_direct_mode(False)

        if surround_name == STRAIGHT:
            parameter = "<Straight>On</Straight>"
        else:
            parameter = "<Sound_Program>{parameter}</Sound_Program>".format(
                parameter=surround_name
            )
        request_text = SurroundProgram.format(parameter=parameter)
        await self._async_request('PUT', request_text)

    async def async_get_scene(self):
        request_text = Scene.format(parameter=GetParam)
        response = await self._async_request('GET', request_text)
        return response.find("%s/Scene/Scene_Sel" % self.zone).text

    async def async_set_scene(self, scene_name):
        assert scene_name in self._device.scenes_number
        scene_number = self._device.scenes_number.get(scene_name)
        request_text = Scene.format(parameter=scene_number)
        await self._async_request('PUT', request_text)

    @property
    def zone(self):
        return self._zone

    @zone.setter
    def zone(self, zone_name):
        assert zone_name in self._device.zones
        self._zone = zone_name

    def zones(self):
        return self._device.zones

    def zone_controllers(self) -> list[RXV]:
        """Return separate RXV controller for each available zone."""
        controllers = []
        for zone in self._device.zones:
            zone_ctrl = copy.copy(self)
            zone_ctrl.zone = zone
            controllers.append(zone_ctrl)
        return controllers

    def supports_method(self, source, *args):
        for parts in self._device.commands:
            if parts[0] == source and parts[1:] == list(args):
                return True
        return False

    def supports_play_method(self, source, method):
        return method in self._device.source_play_methods.get(source, {})

    async def async_is_ready(self):
        src_name = await self._async_get_src_name()
        if not src_name:
            return True  # input is instantly ready

        request_text = ConfigGet.format(src_name=src_name)
        config = await self._async_request('GET', request_text, zone_cmd=False)

        avail = next(config.iter('Feature_Availability'))
        return avail.text == 'Ready'

    @staticmethod
    def safe_get(doc, names):
        for name in names:
            tag = doc.find(".//%s" % name)
            if tag is not None and tag.text is not None:
                # Tuner and Net Radio sometimes respond
                # with escaped entities
                return html.unescape(tag.text).strip()
        return ""

    async def _async_get_src_name(self, cur_input=None):
        if cur_input is None:
            cur_input = await self.async_get_input()
        if cur_input not in self._device.inputs_source:
            return None, None
        if cur_input.upper().startswith('HDMI'):
            # CEC commands can be sent over the HDMI inputs to control devices
            # connected to the receiver. These can support play methods as well
            # as menu cursor commands. Return the zone so these features
            # will be enabled.
            return self.zone, cur_input
        return self._device.inputs_source.get(cur_input), cur_input

    async def async_get_play_status(self, input_source=None):

        src_name = await self._async_get_src_name(input_source)

        if not src_name:
            return None

        if not self.supports_method(src_name, 'Play_Info'):
            return None

        request_text = PlayGet.format(src_name=src_name)
        res = await self._async_request('GET', request_text, zone_cmd=False)

        playing = RXV.safe_get(res, ["Playback_Info"]) == "Play" \
            or src_name == "Tuner"

        status = PlayStatus(
            playing,
            artist=RXV.safe_get(res, ARTIST_OPTIONS),
            album=RXV.safe_get(res, ALBUM_OPTIONS),
            song=RXV.safe_get(res, SONG_OPTIONS),
            station=RXV.safe_get(res, STATION_OPTIONS)
        )
        return status

    async def async_get_menu_status(self):
        src_name, cur_input = await self._async_get_src_name()
        if not src_name:
            raise MenuUnavailable(cur_input)

        request_text = ListGet.format(src_name=src_name)
        res = await self._async_request('GET', request_text, zone_cmd=False)

        ready = (next(res.iter("Menu_Status")).text == "Ready")
        layer = int(next(res.iter("Menu_Layer")).text)
        name = next(res.iter("Menu_Name")).text
        current_line = int(next(res.iter("Current_Line")).text)
        max_line = int(next(res.iter("Max_Line")).text)
        current_list = next(res.iter('Current_List'))

        cl = {
            elt.tag: elt.find('Txt').text
            for elt in list(current_list)
            if elt.find('Attribute').text != 'Unselectable'
        }

        status = MenuStatus(ready, layer, name, current_line, max_line, cl)
        return status

    async def async_set_menu_jump_line(self, lineno):
        src_name, cur_input = await self._async_get_src_name()
        if not src_name:
            raise MenuUnavailable(cur_input)

        request_text = ListControlJumpLine.format(
            src_name=src_name,
            lineno=lineno
        )
        return await self._async_request('PUT', request_text, zone_cmd=False)

    async def async_get_supported_cursor_actions(self, src_name=None):
        if src_name is None:
            src_name = await self._async_get_src_name()
        if not src_name:
            return frozenset()
        cursor_actions = self._device.source_cursor_actions.get(src_name)
        if cursor_actions is None:
            return frozenset()
        return frozenset(action for action in cursor_actions)

    async def async_set_menu_cursor(self, action):
        src_name, cur_input = await self._async_get_src_name()
        if not src_name:
            raise MenuUnavailable(cur_input)

        if self.supports_method(src_name, 'List_Control', 'Cursor'):
            template = ListControlCursor
        elif self.supports_method(src_name, 'Cursor_Control', 'Cursor'):
            template = CursorControlCursor
        else:
            raise MenuUnavailable(cur_input)

        # Check that the specific action is available for the input.
        if action not in await self.async_get_supported_cursor_actions(src_name):
            raise MenuActionUnavailable(cur_input, action)

        request_text = template.format(
            src_name=src_name,
            action=action
        )
        return await self._async_request('PUT', request_text, zone_cmd=False)

    async def async_menu_up(self):
        return await self.async_set_menu_cursor(Cursor.UP)

    async def async_menu_down(self):
        return await self.async_set_menu_cursor(Cursor.DOWN)

    async def async_menu_left(self):
        return await self.async_set_menu_cursor(Cursor.LEFT)

    async def async_menu_right(self):
        return await self.async_set_menu_cursor(Cursor.RIGHT)

    async def async_menu_sel(self):
        return await self.async_set_menu_cursor(Cursor.SEL)

    async def async_menu_return(self):
        return await self.async_set_menu_cursor(Cursor.RETURN)

    async def async_menu_return_to_home(self):
        return await self.async_set_menu_cursor(Cursor.RETURN_TO_HOME)

    async def async_menu_on_screen(self):
        return await self.async_set_menu_cursor(Cursor.ON_SCREEN)

    async def async_menu_top_menu(self):
        return await self.async_set_menu_cursor(Cursor.TOP_MENU)

    async def async_menu_menu(self):
        return await self.async_set_menu_cursor(Cursor.MENU)

    async def async_menu_option(self):
        return await self.async_set_menu_cursor(Cursor.OPTION)

    async def async_menu_display(self):
        return await self.async_set_menu_cursor(Cursor.DISPLAY)

    async def async_menu_reset(self):
        while self.menu_status().layer > 1:
            self.menu_return()

    async def async_get_volume(self):
        request_text = VolumeLevel.format(value=GetParam)
        response = await self._async_request('GET', request_text)
        vol = response.find('%s/Volume/Lvl/Val' % self.zone).text
        return float(vol) / 10.0

    async def async_set_volume(self, value):
        """Convert volume for setting.

        We're passing around volume in standard db units, like -52.0
        db. The API takes int values. However, the API also only takes
        int values that corespond to half db steps (so -52.0 and -51.5
        are valid, -51.8 is not).

        Through the power of math doing the int of * 2, then * 5 will
        ensure we only get half steps.
        """
        value = str(int(value * 2) * 5)
        exp = 1
        unit = 'dB'

        volume_val = VolumeLevelValue.format(val=value, exp=exp, unit=unit)
        request_text = VolumeLevel.format(value=volume_val)
        await self._async_request('PUT', request_text)

    async def async_volume_fade(self, final_vol, sleep=0.5):
        start_vol = int(floor(await self.async_get_volume()))
        step = 1 if final_vol > start_vol else -1
        final_vol += step  # to make sure, we don't stop one dB before

        for val in range(start_vol, final_vol, step):
            await self.async_set_volume(val)
            asyncio.sleep(sleep)

    async def async_is_partymode(self):
        request_text = PartyMode.format(state=GetParam)
        response = await self._async_request('GET', request_text, False)
        pmode = response.find('System/Party_Mode/Mode').text
        assert pmode in ["On", "Off"]
        return pmode == "On"

    async def async_set_partymode(self, on):
        assert on in [True, False]
        new_state = "On" if on else "Off"
        request_text = PartyMode.format(state=new_state)
        response = await self._async_request('PUT', request_text, False)
        return response

    async def async_is_mute(self):
        request_text = VolumeMute.format(state=GetParam)
        response = await self._async_request('GET', request_text)
        mute = response.find('%s/Volume/Mute' % self.zone).text
        assert mute in ["On", "Off"]
        return mute == "On"

    async def async_set_mute(self, mute):
        assert mute in [True, False]
        new_state = "On" if mute else "Off"
        request_text = VolumeMute.format(state=new_state)
        response = await self._async_request('PUT', request_text)
        return response

    async def async_is_adaptive_drc(self):
        """
        View the current Adaptive Dynamic Range Compression setting, a means
        of equalizing various input levels at low volume. This feature is ideal
        for watching late at night (to avoid extremes of volume between
        dialogue scenes and explosions etc.) or in noisy environments. It is
        best disabled for the full dynamic range audio experience.

        :return: True if Dynamic Range Compression is enabled.
        """
        get_tag = '<Adaptive_DRC>GetParam</Adaptive_DRC>'
        request_text = SoundVideo.format(value=get_tag)
        response = await self._async_request('GET', request_text)
        drc = response.find('%s/Sound_Video/Adaptive_DRC' % self.zone).text
        return False if drc == 'Off' else True

    async def async_set_adaptive_drc(self, auto=False):
        """
        :param value: True to enable dynamic range compression. Default False.
        """
        set_value = 'Auto' if auto else 'Off'
        set_tag = '<Adaptive_DRC>{}</Adaptive_DRC>'.format(set_value)
        request_text = SoundVideo.format(value=set_tag)
        await self._async_request('PUT', request_text)

    async def async_get_dialogue_level(self):
        """
        An adjustment to elevate the volume of dialogue sounds; useful if the
        volume of dialogue is difficult to make out against background sounds
        or music.

        :return: An integer between 0 (no adjustment) to 3 (most increased).
        """
        if self.supports_method(self.zone, "Sound_Video", "Dialogue_Adjust", "Dialogue_Lvl"):
            raise CommandUnavailable(self.zone, "Dialogue_Lvl")

        get_tag = '<Dialogue_Adjust><Dialogue_Lvl>GetParam' \
                  '</Dialogue_Lvl></Dialogue_Adjust>'
        request_text = SoundVideo.format(value=get_tag)
        response = await self._async_request('GET', request_text)
        level = response.find('%s/Sound_Video/Dialogue_Adjust/Dialogue_Lvl'
                              % self.zone).text
        return int(level)

    async def async_set_dialogue_level(self, value=0):
        """
        :param value: An integer between 0 and 3 to determine how much to
            increase dialogue sounds over other sounds. A value of zero
            disables this feature.
        """
        if self.supports_method(self.zone, "Sound_Video", "Dialogue_Adjust", "Dialogue_Lvl"):
            raise CommandUnavailable(self.zone, "Dialogue_Lvl")

        if int(value) not in [0, 1, 2, 3]:
            raise ValueError("Value must be 0, 1, 2, or 3")
        set_tag = '<Dialogue_Adjust><Dialogue_Lvl>{}' \
                  '</Dialogue_Lvl></Dialogue_Adjust>'.format(int(value))
        request_text = SoundVideo.format(value=set_tag)
        await self._async_request('PUT', request_text)

    async def _async_set_direct_sel(self, lineno):
        request_text = SelectNetRadioLine.format(lineno=lineno)
        return await self._async_request('PUT', request_text, zone_cmd=False)

    async def async_set_net_radio(self, path):
        """Play net radio at the specified path.

        This lets you play a NET_RADIO address in a single command
        with by encoding it with > as separators. For instance:

            Bookmarks>Internet>Radio Paradise

        It does this by push commands, then looping and making sure
        the menu is in a ready state before we try to push the next
        one. A sufficient number of iterations are allowed for to
        ensure we give it time to get there.

        TODO: better error handling if we some how time out
        TODO: multi page menus (scrolling down)
        """
        layers = path.split(">")
        await self.async_set_input(INPUT_NET_RADIO)
        await self.async_menu_reset()

        for attempt in range(20):
            menu = await self.async_get_menu_status()
            if menu.ready:
                for line, value in menu.current_list.items():
                    if value == layers[menu.layer - 1]:
                        lineno = line[5:]
                        await self._async_set_direct_sel(lineno)
                        if menu.layer == len(layers):
                            return
                        break
            else:
                # print("Sleeping because we are not ready yet")
                asyncio.sleep(1)

    async def _async_set_direct_sel_server(self, lineno):
        request_text = SelectServerLine.format(lineno=lineno)
        return await self._async_request('PUT', request_text, zone_cmd=False)

    async def async_set_server(self, path):
        """Play from specified server

        This lets you play a SERVER address in a single command
        with by encoding it with > as separators. For instance:

            Server>Playlists>GoodVibes

        This code is copied from the net_radio function.

        TODO: better error handling if we some how time out
        """
        layers = path.split(">")
        await self.async_set_input(INPUT_SERVER)

        for attempt in range(20):
            menu = await self.async_get_menu_status()
            if menu.ready:
                for line, value in menu.current_list.items():
                    if value == layers[menu.layer - 1]:
                        lineno = line[5:]
                        await self._async_set_direct_sel_server(lineno)
                        if menu.layer == len(layers):
                            return
                        break
            else:
                # print("Sleeping because we are not ready yet")
                asyncio.sleep(1)

    async def async_get_sleep(self):
        request_text = PowerControlSleep.format(sleep_value=GetParam)
        response = await self._async_request('GET', request_text)
        sleep = response.find("%s/Power_Control/Sleep" % self._zone).text
        return sleep

    async def async_set_sleep(self, value):
        request_text = PowerControlSleep.format(sleep_value=value)
        await self._async_request('PUT', request_text)

    @property
    def small_image_url(self):
        return f"http://{self.host}:8080/BCO_device_sm_icon.png"

    @property
    def large_image_url(self):
        return f"http://{self.host}:8080/BCO_device_lrg_icon.png"