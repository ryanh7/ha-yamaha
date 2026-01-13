from __future__ import annotations
from dataclasses import asdict
import logging
from uuid import uuid4
from typing import Any, cast
from .rxv import RXV, async_discover_device_info
from .utils import get_id_from_udn, get_store
import voluptuous as vol
from urllib.parse import urlparse
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME, CONF_HOST
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_FRIENDLY_NAME,
    ATTR_UPNP_SERIAL,
    ATTR_UPNP_UDN,
    SsdpServiceInfo,
)


from .const import CONF_BASE_URL, CONF_INFO_ID, CONF_SSDP_LOCATION, DEFAULT_NAME, DOMAIN

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
        
        return self.async_create_entry(title=f"{rxv.friendly_name or DEFAULT_NAME} ({rxv.serial_number})", data={CONF_HOST: host})

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            ssdp_location = f"http://{user_input[CONF_HOST]}:8080/MediaRenderer/desc.xml"
            rxv_device_info, base_url = await async_discover_device_info(self.hass, ssdp_location)
            if not rxv_device_info or not base_url:
                return self.async_abort(reason="no_desc")
            
            device_id = rxv_device_info.device_id
            if not device_id:
                return self.async_abort(reason="no_uuid")
            
            await self.async_set_unique_id(f"{DOMAIN}.{device_id}")
            self._abort_if_unique_id_configured()

            info_id = str(uuid4())
            await get_store(self.hass, info_id).async_save(asdict(rxv_device_info))
            data = {
                CONF_SSDP_LOCATION: ssdp_location,
                CONF_BASE_URL: base_url,
                CONF_INFO_ID: info_id
            }
            return self.async_create_entry(title=f"{rxv_device_info.friendly_name} ({rxv_device_info.serial_number})", data=data)


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
        placeholders = {"host": cast(str, urlparse(self._ssdp_location).hostname)}
        #self.context["title_placeholders"] = placeholders

        if user_input is not None:
            self._abort_if_unique_id_configured()
            info_id = str(uuid4())
            await get_store(self.hass, info_id).async_save(asdict(self._device))
            data = {
                CONF_SSDP_LOCATION: self._ssdp_location,
                CONF_BASE_URL: self._base_url,
                CONF_INFO_ID: info_id
            }
            return self.async_create_entry(title=f"{self.friendly_name} ({self.serial_number})", data=data)

        return self.async_show_form(
            step_id="confirm", description_placeholders=placeholders
        )
    
    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a discovered device."""
        ssdp_location = discovery_info.ssdp_location

        device_id = get_id_from_udn(discovery_info.upnp.get(ATTR_UPNP_UDN))
    
        if not device_id:
            return self.async_abort(reason="no_uuid")

        existed_entry = await self.async_set_unique_id(f"{DOMAIN}.{device_id}")
        if existed_entry and existed_entry.data.get(CONF_SSDP_LOCATION) == ssdp_location:
            return self.async_abort(reason="already_configured")
        
        rxv_device_info, base_url = await async_discover_device_info(self.hass, discovery_info.ssdp_location)
        if not rxv_device_info or not base_url:
            return self.async_abort(reason="no_desc")
        
        self._abort_if_unique_id_configured({
            CONF_SSDP_LOCATION: ssdp_location,
            CONF_BASE_URL: base_url
        })

        self._device = rxv_device_info
        self._ssdp_location = ssdp_location
        self._base_url = base_url
        
        self.friendly_name = discovery_info.upnp.get(ATTR_UPNP_FRIENDLY_NAME) or DEFAULT_NAME
        self.serial_number = discovery_info.upnp.get(ATTR_UPNP_SERIAL)
        self.context.update({
            "title_placeholders": {
                CONF_NAME: f"{self.friendly_name} {self.serial_number}".strip(),
            }
        })

        return await self.async_step_confirm()

