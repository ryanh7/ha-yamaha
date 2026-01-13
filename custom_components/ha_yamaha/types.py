from dataclasses import dataclass


@dataclass
class RXVDeviceInfo:
    control_url: str
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