# https://github.com/esphome/esphome/blob/dev/esphome/components/daly_bms/__init__.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID
from esphome.components.canbus import CanbusComponent

CONF_TT_ID = "toptronic_id"
CONF_CANBUS_ID = "canbus_id"
CONF_DECIMAL = "decimal"

toptronic = cg.esphome_ns.namespace("toptronic")
TopTronicComponent = toptronic.class_(
    "TopTronic", cg.Component
)

TopTronicBase = toptronic.class_(
    "TopTronicBase", cg.PollingComponent
)

TT_TYPE = toptronic.enum("TypeName")
TT_TYPE_OPTIONS = {
    "U8": TT_TYPE.U8,
    "U16": TT_TYPE.U16,
    "U32": TT_TYPE.U32,
    "S8": TT_TYPE.S8,
    "S16": TT_TYPE.S16,
    "S32": TT_TYPE.S32,
    "S64": TT_TYPE.S64,
}


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
).extend(cv.polling_component_schema("30s"))

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