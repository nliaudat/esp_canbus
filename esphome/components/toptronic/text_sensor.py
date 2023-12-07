# https://github.com/esphome/esphome/blob/dev/esphome/components/fs3000/sensor.py
# https://github.com/esphome/esphome/blob/dev/esphome/components/daly_bms/sensor.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import text_sensor
from esphome.const import (
    CONF_VALUE,
    CONF_OPTIONS,
)
from . import (
    toptronic, 
    CONF_TT_ID, 
    TopTronicComponent,

    CONFIG_SCHEMA_BASE,
    CONF_DEVICE_TYPE,
    CONF_DEVICE_ADDR,
    CONF_FUNCTION_GROUP,
    CONF_FUNCTION_NUMBER,
    CONF_DATAPOINT,
    CONF_VALUES,
)

TopTronicTextSensor = toptronic.class_(
    "TopTronicTextSensor", text_sensor.TextSensor
)

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(CONF_TT_ID): cv.use_id(TopTronicComponent),
    cv.Required(CONF_OPTIONS): cv.All(
        cv.ensure_list(cv.string_strict), cv.Length(min=1)
    ),
    cv.Required(CONF_VALUES): cv.All(
        cv.ensure_list(cv.int_), cv.Length(min=1)
    ),
}).extend(text_sensor.text_sensor_schema(
    TopTronicTextSensor
)).extend(CONFIG_SCHEMA_BASE)

async def to_code(config):
    tt = await cg.get_variable(config[CONF_TT_ID])
    sens = await text_sensor.new_text_sensor(config)
   
    cg.add(sens.set_device_type(config[CONF_DEVICE_TYPE]))
    cg.add(sens.set_device_addr(config[CONF_DEVICE_ADDR]))
    cg.add(sens.set_function_group(config[CONF_FUNCTION_GROUP]))
    cg.add(sens.set_function_number(config[CONF_FUNCTION_NUMBER]))
    cg.add(sens.set_datapoint(config[CONF_DATAPOINT]))
    
    for i in range(len(config[CONF_OPTIONS])):
        value = config[CONF_VALUES][i]
        text = config[CONF_OPTIONS][i]
        cg.add(sens.add_option(value, text))
    
    cg.add(tt.add_sensor(sens))