import pathlib
from enum import Enum

import yaml

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components.canbus import CanbusComponent
from esphome.const import CONF_ID
from esphome.core import CORE, ID
from esphome.cpp_types import Component

CODEOWNERS = ["@nliaudat"]
DEPENDENCIES = ["canbus"]
AUTO_LOAD = ["sensor", "number", "select", "text_sensor", "button"]
MULTI_CONF = True

CONF_TT_ID = "toptronic_id"
CONF_CANBUS_ID = "canbus_id"
CONF_DEVICE_TYPE = "device_type"
CONF_DEVICE_ADDR = "device_addr"
CONF_FUNCTION_GROUP = "function_group"
CONF_FUNCTION_NUMBER = "function_number"
CONF_DATAPOINT = "datapoint"
CONF_DECIMAL = "decimal"
CONF_VALUES = "values"
CONF_LANGUAGE = "language"
CONF_USE_CANBUS_CALLBACK = "use_canbus_callback"
CONF_BOOT_REFRESH_DELAY = "boot_refresh_delay"

LANGS = ("de", "en", "fr", "it")

toptronic = cg.esphome_ns.namespace("toptronic")
TopTronicComponent = toptronic.class_("TopTronic", cg.Component)

TopTronicBase = toptronic.class_("TopTronicBase", cg.PollingComponent)

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
    WEZ = 0     # EN: Heat generator / FR: Générateur de chaleur / DE: Wärmeerzeuger
    SOL = 64    # EN: Solar module / FR: Module solaire / DE: Solar
    PS = 128    # EN: Buffer storage tank / FR: Ballon tampon / DE: Pufferspeicher
    FW = 192    # EN: District heating / FR: Chauffage urbain / DE: Fernwärme
    HK = 256    # EN: Heating circuit / FR: Circuit de chauffage / DE: Heizkreis
    MWA = 384   # EN: Energy meter module / FR: Module de mesure d'énergie / DE: Messwertauswertung
    GLT = 448   # EN: Building mgmt system (BMS) / FR: Gestion technique du bâtiment (GTB) / DE: Gebäudeleittechnik
    HV = 512    # EN: HomeVent ventilation / FR: Ventilation HomeVent / DE: HomeVent
    BM = 1024   # EN: Control module (Display) / FR: Module de commande (Écran) / DE: Bedienmodul
    BD = 1024   # EN: Control display (Alias) / FR: Écran de commande (Alias) / DE: Bediendisplay
    GW = 1153   # EN: Gateway (Modbus/KNX) / FR: Passerelle (Modbus/KNX) / DE: Gateway


_device_types = {t.name: t.value for t in DeviceType}

PRESETS_DIR = pathlib.Path(__file__).parent / "presets"

_IDS_KEY = "toptronic_used_ids"


def _shared_used_ids():
    """Build-wide set of used IDs, shared across all hub instances."""
    if _IDS_KEY not in CORE.data:
        CORE.data[_IDS_KEY] = set()
    return CORE.data[_IDS_KEY]


def get_device_type(t: str) -> int:
    if t not in _device_types:
        raise ValueError(f'device type "{t}" not found')
    return _device_types.get(t)


def _validate_preset(config):
    device_type = config[CONF_DEVICE_TYPE]
    if device_type not in _device_types:
        raise cv.Invalid(f"Device type '{device_type}' is not a known TopTronic device type")
    if not (PRESETS_DIR / device_type).is_dir():
        raise cv.Invalid(
            f"No preset directory found for device type '{device_type}'. "
            "Available presets: WEZ, HV, BM"
        )
    return config


CONFIG_SCHEMA_BASE = cv.Schema(
    {
        cv.Required(CONF_FUNCTION_GROUP): cv.uint8_t,
        cv.Required(CONF_FUNCTION_NUMBER): cv.uint8_t,
        cv.Required(CONF_DATAPOINT): cv.uint16_t,
    }
).extend(cv.polling_component_schema("30s"))

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(TopTronicComponent),
            cv.GenerateID(CONF_CANBUS_ID): cv.use_id(CanbusComponent),
            cv.Required(CONF_DEVICE_TYPE): cv.one_of(
                *[t.name for t in DeviceType], upper=True
            ),
            cv.Required(CONF_DEVICE_ADDR): cv.uint8_t,
            cv.Optional(CONF_LANGUAGE, default="en"): cv.one_of(*LANGS, lower=True),
            cv.Optional(CONF_USE_CANBUS_CALLBACK, default=True): cv.boolean,
            cv.Optional(
                CONF_BOOT_REFRESH_DELAY, default="30s"
            ): cv.positive_time_period_milliseconds,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    _validate_preset,
)


def _load_entities(device_type: str, language: str):
    entities = []
    for kind in ("sensors", "inputs", "buttons"):
        path = PRESETS_DIR / device_type / f"{kind}_{language}.yaml"
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for platform_name, entries in data.items():
            for entry in entries or []:
                entities.append((platform_name, dict(entry)))
    return entities


def _resolve_ids(obj, used=None):
    """Resolve auto-generated IDs inside a validated entity config.

    Entities synthesized from presets bypass config.py's global ID pass, so
    nested IDs (e.g. filter IDs) keep id=None. Resolve them now to avoid
    duplicate empty-ID registrations during code generation, and record
    Component-derived declarations in CORE.component_ids as config.py would.
    """
    if used is None:
        used = set()
    if isinstance(obj, ID):
        if obj.id is None:
            obj.resolve(used)
        used.add(obj.id)
        if obj.is_declaration and isinstance(obj.type, cg.MockObjClass) and obj.type.inherits_from(
            Component
        ):
            CORE.component_ids.add(obj.id)
    elif isinstance(obj, dict):
        for value in obj.values():
            _resolve_ids(value, used)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _resolve_ids(value, used)
    return used


async def _generate_entities(hub, config):
    from . import button, number, select, sensor, text_sensor

    platforms = {
        "sensor": (sensor.CONFIG_SCHEMA, sensor.to_code),
        "text_sensor": (text_sensor.CONFIG_SCHEMA, text_sensor.to_code),
        "number": (number.CONFIG_SCHEMA, number.to_code),
        "select": (select.CONFIG_SCHEMA, select.to_code),
        "button": (button.CONFIG_SCHEMA, button.to_code),
    }

    used_ids = _shared_used_ids()
    for platform_name, entity_conf in _load_entities(
        config[CONF_DEVICE_TYPE], config[CONF_LANGUAGE]
    ):
        if platform_name not in platforms:
            raise cv.Invalid(
                f"Unsupported platform '{platform_name}' in toptronic preset"
            )
        entity_conf.pop("platform", None)
        entity_conf.pop(CONF_DEVICE_TYPE, None)
        entity_conf.pop(CONF_DEVICE_ADDR, None)
        hub_ref = config[CONF_ID].copy()
        hub_ref.is_declaration = False
        entity_conf[CONF_TT_ID] = hub_ref

        schema, codegen = platforms[platform_name]
        validated = schema(entity_conf)
        _resolve_ids(validated, used_ids)
        await codegen(validated)


async def to_code(config):
    cbus = await cg.get_variable(config[CONF_CANBUS_ID])
    var = cg.new_Pvariable(config[CONF_ID], cbus)
    await cg.register_component(var, config)

    device_type = get_device_type(config[CONF_DEVICE_TYPE])
    cg.add(var.set_device_type(device_type))
    cg.add(var.set_device_addr(config[CONF_DEVICE_ADDR]))
    cg.add(var.set_use_canbus_callback(config[CONF_USE_CANBUS_CALLBACK]))
    cg.add(var.set_boot_refresh_delay(config[CONF_BOOT_REFRESH_DELAY]))

    await _generate_entities(var, config)
