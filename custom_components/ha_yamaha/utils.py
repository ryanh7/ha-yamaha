from homeassistant.helpers.storage import Store
from homeassistant.helpers.json import JSONEncoder
from .const import DOMAIN


STORAGE_VERSION = 1


def get_store(hass, config_entry_id: str) -> Store[str]:
    """Return the reolink store."""
    return Store(
        hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry_id}", encoder=JSONEncoder
    )

def get_id_from_udn(udn):
    return udn[5:].split("-")[4]