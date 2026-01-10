from homeassistant.helpers.storage import Store
from homeassistant.helpers.json import JSONEncoder
import re
from .const import DOMAIN


STORAGE_VERSION = 3


def get_store(hass, config_entry_id: str) -> Store[str]:
    """Return the reolink store."""
    return Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry_id}", encoder=JSONEncoder
    )

def get_id_from_udn(udn):
    if udn is None:
        return None
    
    if not isinstance(udn, str):
        return None
    
    # 定义正则表达式模式，匹配以"uuid:"开头，后面跟UUID格式的字符串
    pattern = r'^uuid:([A-Za-z0-9\-]+)$'
    
    # 使用re.match进行匹配
    match = re.match(pattern, udn, re.IGNORECASE)
    
    if match:
        # 如果匹配成功，返回UUID部分
        return match.group(1)
    else:
        # 如果匹配失败，返回None
        return None