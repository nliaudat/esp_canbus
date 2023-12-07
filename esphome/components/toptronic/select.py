# https://github.com/esphome/esphome/blob/dev/esphome/components/template/select/__init__.py
import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import select
from esphome.components.canbus import CanbusComponent
from esphome.const import (
    CONF_ID,
    CONF_OPTIONS,
)
from . import (
    toptronic, 
    CONF_TT_ID, 
    CONF_CANBUS_ID,
    TopTronicComponent,

    CONFIG_SCHEMA_BASE,
    CONF_DEVICE_TYPE,
    CONF_DEVICE_ADDR,
    CONF_FUNCTION_GROUP,
    CONF_FUNCTION_NUMBER,
    CONF_DATAPOINT,
    CONF_VALUES,
)

TopTronicSelect = toptronic.class_(
    "TopTronicSelect", select.Select
)

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(CONF_TT_ID): cv.use_id(TopTronicComponent),
    cv.GenerateID(CONF_CANBUS_ID): cv.use_id(CanbusComponent),
    cv.Required(CONF_OPTIONS): cv.All(
        cv.ensure_list(cv.string_strict), cv.Length(min=1)
    ),
    cv.Required(CONF_VALUES): cv.All(
        cv.ensure_list(cv.int_), cv.Length(min=1)
    ),
}).extend(select.select_schema(
    TopTronicSelect
)).extend(CONFIG_SCHEMA_BASE)

async def new_select(config, *, options: list[str]):
    cbus = await cg.get_variable(config[CONF_CANBUS_ID])
    var = cg.new_Pvariable(config[CONF_ID], cbus)
    await select.register_select(var, config, options=options)
    return var

async def to_code(config):
    tt = await cg.get_variable(config[CONF_TT_ID])
    var = await new_select(config, options=config[CONF_OPTIONS])
   
    cg.add(var.set_device_type(config[CONF_DEVICE_TYPE]))
    cg.add(var.set_device_addr(config[CONF_DEVICE_ADDR]))
    cg.add(var.set_function_group(config[CONF_FUNCTION_GROUP]))
    cg.add(var.set_function_number(config[CONF_FUNCTION_NUMBER]))
    cg.add(var.set_datapoint(config[CONF_DATAPOINT]))
    
    for i in range(len(config[CONF_OPTIONS])):
        value = config[CONF_VALUES][i]
        text = config[CONF_OPTIONS][i]
        cg.add(var.add_option(value, text))

    cg.add(tt.add_input(var))