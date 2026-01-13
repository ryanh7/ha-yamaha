from dataclasses import asdict
import re

from homeassistant.helpers.json import JSONEncoder
from homeassistant.helpers.storage import Store
from homeassistant.util.uuid import random_uuid_hex

from .const import DOMAIN
from .types import RXVDeviceInfo

STORAGE_VERSION = 3


def get_store(hass, info_id: str) -> Store[str]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{info_id}", encoder=JSONEncoder)


async def async_save_store(hass, device_info: RXVDeviceInfo, info_id=None) -> str:
    if not info_id:
        info_id = random_uuid_hex()

    await get_store(hass, info_id).async_save(asdict(device_info))
    return info_id


async def async_remove_store(hass, info_id):
    await get_store(hass, info_id).async_remove()


def get_id_from_udn(udn):
    if udn is None:
        return None

    if not isinstance(udn, str):
        return None

    # 定义正则表达式模式，匹配以"uuid:"开头，后面跟UUID格式的字符串
    pattern = r"^uuid:([A-Za-z0-9\-]+)$"

    # 使用re.match进行匹配
    match = re.match(pattern, udn, re.IGNORECASE)

    if match:
        # 如果匹配成功，返回UUID部分
        return match.group(1)
    # 如果匹配失败，返回None
    return None
