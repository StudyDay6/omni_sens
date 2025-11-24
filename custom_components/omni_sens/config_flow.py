"""Config flow for Omni Sens."""
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_ENABLE_SCANNING,
    CONF_SCAN_INTERVAL,
    CONF_DEVICE_NAME_FILTER,
    CONF_ENABLE_SCANNING,
)


class OmniSensConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Omni Sens."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # 检查是否已经配置过（如果需要单实例）
            # await self.async_set_unique_id(DOMAIN)
            # self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=DEFAULT_NAME,
                data=user_input,
            )

        data_schema = {
            vol.Required(CONF_ENABLE_SCANNING, default=DEFAULT_ENABLE_SCANNING): bool,
            vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=300)
            ),
            vol.Optional(CONF_DEVICE_NAME_FILTER, default=""): str,
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OmniSensOptionsFlow(config_entry)


class OmniSensOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Omni Sens."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_SCANNING,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_SCANNING, DEFAULT_ENABLE_SCANNING
                        ),
                    ): bool,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=300)),
                    vol.Optional(
                        CONF_DEVICE_NAME_FILTER,
                        default=self.config_entry.options.get(CONF_DEVICE_NAME_FILTER, ""),
                    ): str,
                }
            ),
        )

