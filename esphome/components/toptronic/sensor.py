# https://github.com/esphome/esphome/blob/dev/esphome/components/fs3000/sensor.py
# https://github.com/esphome/esphome/blob/dev/esphome/components/daly_bms/sensor.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import sensor
from esphome.const import (
    CONF_TYPE
)
from . import toptronic, CONF_TT_ID, TopTronicComponent

TopTronicSensor = toptronic.class_(
    "TopTronicSensor", sensor.Sensor
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

CONFIG_SCHEMA = (
    sensor.sensor_schema(
        TopTronicSensor
    )
    .extend(
        {
            cv.GenerateID(CONF_TT_ID): cv.use_id(TopTronicComponent),
            cv.Required(CONF_DEVICE_TYPE): cv.uint8_t,
            cv.Required(CONF_DEVICE_ADDR): cv.uint8_t,

            cv.Required(CONF_FUNCTION_GROUP): cv.uint8_t,
            cv.Required(CONF_FUNCTION_NUMBER): cv.uint8_t,
            cv.Required(CONF_DATAPOINT): cv.uint16_t,
            cv.Required(CONF_TYPE): cv.enum(TT_TYPE_OPTIONS),
        }
    )
)

async def to_code(config):
    tt = await cg.get_variable(config[CONF_TT_ID])
    sens = await sensor.new_sensor(config)
   
    cg.add(sens.set_device_type(config[CONF_DEVICE_TYPE]))
    cg.add(sens.set_device_addr(config[CONF_DEVICE_ADDR]))
    cg.add(sens.set_function_group(config[CONF_FUNCTION_GROUP]))
    cg.add(sens.set_function_number(config[CONF_FUNCTION_NUMBER]))
    cg.add(sens.set_datapoint(config[CONF_DATAPOINT]))
    cg.add(sens.set_type(config[CONF_TYPE]))
    
    cg.add(tt.add_sensor(sens))