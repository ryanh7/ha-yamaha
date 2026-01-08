from __future__ import annotations
import logging
from typing import Any
from .rxv import RXV
from .utils import get_id_from_udn
import voluptuous as vol
from urllib.parse import urlparse
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, SOURCE_SSDP
from homeassistant.const import CONF_NAME, CONF_HOST, CONF_SOURCE
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_FRIENDLY_NAME,
    ATTR_UPNP_SERIAL,
    ATTR_UPNP_UDN,
    SsdpServiceInfo,
)


from .const import DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class YamahaFlowHandler(ConfigFlow, domain=DOMAIN):
    """Config flow for Met Eireann component."""

    VERSION = 1

    async def _async_set_unique_id_and_update(
        self, device_id: str, host: str
    ) -> None:
        await self.async_set_unique_id(f"yamaha-{device_id}")
        self._abort_if_unique_id_configured({CONF_HOST: host})

    async def _async_check_and_create(self, host: str) -> ConfigFlowResult:
        
        try:
            rxv = RXV(self.hass, host)
            await rxv.async_setup()
            device_id = rxv.device_id
        except Exception as error:
            _LOGGER.exception(error)
            return self.async_abort(reason="cannot_connect")

        if not device_id:
            return self.async_abort(reason="cannot_connect")
        
        await self._async_set_unique_id_and_update(device_id, host)
        
        self._abort_if_unique_id_configured()
        
        return self.async_create_entry(title=f"{rxv.friendly_name or DEFAULT_NAME} ({rxv.serial_number})", data={CONF_HOST: host})

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            return await self._async_check_and_create(user_input[CONF_HOST])

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                    {
                        vol.Required(CONF_HOST): str
                    }
            ),
            errors=errors,
        )
    
    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user-confirmation of discovered node."""
        placeholders = {"host": self.host}
        #self.context["title_placeholders"] = placeholders

        if user_input is not None:
            return await self._async_check_and_create(self.host)

        return self.async_show_form(
            step_id="confirm", description_placeholders=placeholders
        )
    
    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a discovered device."""
        host = str(urlparse(discovery_info.ssdp_location).hostname)

        device_id = get_id_from_udn(discovery_info.upnp.get(ATTR_UPNP_UDN))
    
        if not device_id:
            return self.async_abort(reason="no_uuid")

        await self._async_set_unique_id_and_update(device_id, host)
        
        friendly_name = discovery_info.upnp.get(ATTR_UPNP_FRIENDLY_NAME) or "Yamaha Media Render"
        serialNumber = discovery_info.upnp.get(ATTR_UPNP_SERIAL)
        self.context.update({
            "title_placeholders": {
                CONF_NAME: f"{friendly_name} {serialNumber}".strip(),
                CONF_HOST: host
            }
        })

        self.host = host
        return await self.async_step_confirm()

