# https://github.com/esphome/esphome/blob/dev/esphome/components/fs3000/sensor.py
# https://github.com/esphome/esphome/blob/dev/esphome/components/daly_bms/sensor.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import text_sensor
from esphome.const import (
    CONF_VALUE,
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
)

TopTronicTextSensor = toptronic.class_(
    "TopTronicTextSensor", text_sensor.TextSensor
)

CONF_LIST = "list"
CONF_TEXT = "text"

validate_list = cv.Schema({
    cv.Required(CONF_VALUE): cv.uint8_t,
    cv.Required(CONF_TEXT): cv.string,
})

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(CONF_TT_ID): cv.use_id(TopTronicComponent),
    cv.Required(CONF_LIST): cv.ensure_list(validate_list),
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
    
    for option in config[CONF_LIST]:
        cg.add(sens.add_option(option['value'], option['text']))
    
    cg.add(tt.add_sensor(sens))