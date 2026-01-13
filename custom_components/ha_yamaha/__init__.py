from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.start import async_at_started

from .const import CONF_INFO_ID
from .coordinator import YamahaCoordinator
from .utils import async_remove_store

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    rxv = YamahaCoordinator(hass, config_entry=entry)
    await rxv.async_setup()
    entry.runtime_data = rxv

    async def _async_finish_startup(hass: HomeAssistant) -> None:
        """Run this only when HA has finished its startup."""
        await rxv.async_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Don't fetch data during startup, this will slow down the overall startup dramatically
    async_at_started(hass, _async_finish_startup)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    await async_remove_store(hass, config_entry.data.get(CONF_INFO_ID))
