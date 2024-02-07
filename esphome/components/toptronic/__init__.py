# https://github.com/esphome/esphome/blob/dev/esphome/components/daly_bms/__init__.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import CONF_ID
from esphome.components.canbus import CanbusComponent
from enum import Enum

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

class DeviceType(Enum):
    WEZ = 0
    SOL = 64
    PS = 128
    FW = 192
    HK = 256
    MWA = 384
    GLT = 448
    HV = 512
    BD = 1024
    GW = 1153

_device_types = {t.name: t.value for t in DeviceType}

def get_device_type(t: str) -> int:
    if t not in _device_types:
        raise f'device type "{t}" not found'
    return _device_types.get(t)

CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_ADDR = "device_addr"

CONF_FUNCTION_GROUP = "function_group"
CONF_FUNCTION_NUMBER = "function_number"
CONF_DATAPOINT = "datapoint"
CONF_VALUES = "values"

CONFIG_SCHEMA_BASE = cv.Schema(
    {
        cv.Required(CONF_DEVICE_TYPE): cv.string,
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
            cv.Optional(CONF_DEVICE_TYPE, 'GW'): cv.string,
            cv.Optional(CONF_DEVICE_ADDR, 1): cv.uint8_t,
        }
    )
    .extend(cv.COMPONENT_SCHEMA)
)

async def to_code(config):
    cbus = await cg.get_variable(config[CONF_CANBUS_ID])
    var = cg.new_Pvariable(config[CONF_ID], cbus)
    await cg.register_component(var, config)

    device_type = get_device_type(config[CONF_DEVICE_TYPE])
    cg.add(var.set_device_type(device_type))
    cg.add(var.set_device_addr(config[CONF_DEVICE_ADDR]))

