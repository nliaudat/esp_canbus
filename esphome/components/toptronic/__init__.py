# https://github.com/esphome/esphome/blob/dev/esphome/components/daly_bms/__init__.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID
from esphome.components.canbus import CanbusComponent

CONF_TT_ID = "toptronic_id"
CONF_CANBUS_ID = "canbus_id"

toptronic = cg.esphome_ns.namespace("toptronic")
TopTronicComponent = toptronic.class_(
    "TopTronic", cg.Component
)

CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_ADDR = "device_addr"

CONF_FUNCTION_GROUP = "function_group"
CONF_FUNCTION_NUMBER = "function_number"
CONF_DATAPOINT = "datapoint"
CONF_VALUES = "values"

CONFIG_SCHEMA_BASE = cv.Schema(
    {
        cv.Required(CONF_DEVICE_TYPE): cv.uint8_t,
        cv.Required(CONF_DEVICE_ADDR): cv.uint8_t,

        cv.Required(CONF_FUNCTION_GROUP): cv.uint8_t,
        cv.Required(CONF_FUNCTION_NUMBER): cv.uint8_t,
        cv.Required(CONF_DATAPOINT): cv.uint16_t,
    }
)

CONFIG_SCHEMA = (
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(TopTronicComponent),
            cv.GenerateID(CONF_CANBUS_ID): cv.use_id(CanbusComponent),
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)

async def to_code(config):
    cbus = await cg.get_variable(config[CONF_CANBUS_ID])
    var = cg.new_Pvariable(config[CONF_ID], cbus)
    await cg.register_component(var, config)