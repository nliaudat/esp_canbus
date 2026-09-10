from enum import Enum
import pathlib

import esphome.codegen as cg
from esphome.components import button as button_platform
from esphome.components.canbus import CanbusComponent
import esphome.config_validation as cv
from esphome.const import (
    CONF_ENTITY_CATEGORY,
    CONF_ICON,
    CONF_ID,
    CONF_NAME,
    CONF_OPTIONS,
    CONF_SUBSTITUTIONS,
)
from esphome.core import CORE, ID
from esphome.cpp_types import Component
from esphome import yaml_util

CODEOWNERS = ["@nliaudat"]
DEPENDENCIES = ["canbus"]
AUTO_LOAD = ["sensor", "number", "select", "text_sensor", "button", "switch"]
MULTI_CONF = True

CONF_TOPTRONIC_ID = "toptronic_id"
CONF_CANBUS_ID = "canbus_id"
CONF_DEVICE_ADDR = "device_addr"
CONF_FUNCTION_GROUP = "function_group"
CONF_FUNCTION_NUMBER = "function_number"
CONF_DATAPOINT = "datapoint"
CONF_DECIMAL = "decimal"
CONF_VALUES = "values"
CONF_LANGUAGE = "language"
CONF_NAME_PREFIX = "name_prefix"
CONF_BOOT_REFRESH_DELAY = "boot_refresh_delay"
CONF_MAX_PENDING_MESSAGES = "max_pending_messages"
CONF_MAX_PENDING_AGE = "max_pending_age"
CONF_CLEANUP_INTERVAL = "cleanup_interval"
CONF_MAX_REFRESH_PER_LOOP = "max_refresh_per_loop"
CONF_MAX_FRAMES_PER_MESSAGE = "max_frames_per_message"
CONF_REFRESH_GAP_MS = "refresh_gap_ms"
CONF_MAX_REFRESH_RETRIES = "max_refresh_retries"
CONF_REFRESH_RETRY_INTERVAL_MS = "refresh_retry_interval_ms"
CONF_WRITE_MIN_INTERVAL = "write_min_interval"
CONF_REJECT_WRITES_BEFORE_READ = "reject_writes_before_read"

LANGS = ("de", "en", "fr", "it")

toptronic = cg.esphome_ns.namespace("toptronic")
TopTronicComponent = toptronic.class_("TopTronic", cg.Component)

TopTronicBase = toptronic.class_("TopTronicBase", cg.PollingComponent)

# Auto-generated "Refresh all" button (one per build). press_action() calls the
# parent hub's refresh_all(), which fans out to every registered hub.
TopTronicRefreshButton = toptronic.class_(
    "TopTronicRefreshButton", button_platform.Button, cg.Component
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
    WEZ = 0  # EN: Heat generator / FR: Générateur de chaleur / DE: Wärmeerzeuger
    SOL = 64  # EN: Solar module / FR: Module solaire / DE: Solar
    PS = 128  # EN: Buffer storage tank / FR: Ballon tampon / DE: Pufferspeicher
    FW = 192  # EN: District heating / FR: Chauffage urbain / DE: Fernwärme
    HK = 256  # EN: Heating circuit / FR: Circuit de chauffage / DE: Heizkreis
    MWA = 384  # EN: Energy meter module / FR: Module de mesure d'énergie / DE: Messwertauswertung
    GLT = 448  # EN: Building mgmt system (BMS) / FR: Gestion technique du bâtiment (GTB) / DE: Gebäudeleittechnik
    HV = 512  # EN: HomeVent ventilation / FR: Ventilation HomeVent / DE: HomeVent
    BM = 1024  # EN: Control module (Display) / FR: Module de commande (Écran) / DE: Bedienmodul
    BD = BM  # EN: Control display (Alias) / FR: Écran de commande (Alias) / DE: Bediendisplay
    GW = 1153  # EN: Gateway (Modbus/KNX) / FR: Passerelle (Modbus/KNX) / DE: Gateway


_device_types = {t.name: t.value for t in DeviceType}

PRESETS_DIR = pathlib.Path(__file__).parent / "presets"

_IDS_KEY = "toptronic_used_ids"


def _shared_used_ids():
    """Build-wide set of used IDs, shared across all hub instances."""
    if _IDS_KEY not in CORE.data:
        CORE.data[_IDS_KEY] = set()
    return CORE.data[_IDS_KEY]


def _hub_entries():
    """Return the configured toptronic hub entries as a list.

    ``CORE.config`` holds the raw config, where a single ``toptronic:`` block is
    a mapping rather than a list, so normalise before iterating.
    """
    hubs = CORE.config.get("toptronic", []) if CORE.config else []
    if isinstance(hubs, dict):
        hubs = [hubs]
    return hubs


def get_device_type(t: str) -> int:
    if t not in _device_types:
        raise ValueError(f'device type "{t}" not found')
    return _device_types.get(t)


def _hub_bus_id(hub):
    """Return a hub's canbus_id as a plain string.

    ``CORE.config`` may hold the canbus id as a validated ``ID`` object or as the
    raw string, so normalise both to the underlying identifier.
    """
    bus = hub.get(CONF_CANBUS_ID)
    return getattr(bus, "id", bus)


def _hub_identity(hub):
    """Normalise a hub entry to its (canbus_id, device_type, device_addr) identity.

    Works for both the validated hub config and the raw entries in
    ``CORE.config`` (where device_type may still be lower-case and device_addr a
    substituted string).
    """
    device_type = str(hub.get("device_type", "")).upper()
    addr = hub.get(CONF_DEVICE_ADDR)
    try:
        addr = int(addr)
    except (TypeError, ValueError):
        pass
    return (_hub_bus_id(hub), device_type, addr)


def _resolve_hub_prefix(config):
    """Return the name prefix for this hub's generated entities, or None.

    ESPHome validates entity names build-wide (keyed on the sub-device id, the
    platform and the hash of the sanitized name), but the preset names are only
    unique within a single device type. Prefixing with the device type keeps
    every generated entity unique when several hubs are configured:

      * one hub              -> ``None`` (existing names/object_ids unchanged)
      * repeated device type -> ``"<TYPE> <addr>"``
      * repeated type + addr -> ``"<TYPE> <addr> <canbus_id>"`` (two CAN buses)

    An explicit ``name_prefix`` always wins.
    """
    explicit = config.get(CONF_NAME_PREFIX)
    if explicit:
        return explicit.strip()
    hubs = _hub_entries()
    if len(hubs) <= 1:
        return None
    _bus, device_type, addr = _hub_identity(config)
    identities = [_hub_identity(h) for h in hubs]
    if sum(1 for i in identities if i[1] == device_type) <= 1:
        return device_type
    prefix = f"{device_type} {addr}"
    if sum(1 for i in identities if i[1] == device_type and i[2] == addr) > 1:
        # Same device type *and* address on another CAN bus: only the bus id can
        # tell the two hubs (and their identically named entities) apart.
        prefix = f"{prefix} {_hub_bus_id(config)}"
    return prefix


def _sanitize_entity_name(name: str) -> str:
    """Replace '/' with '_' in a generated entity name.

    ESPHome reserves '/' as a URL path separator: 2026.x only warns and
    substitutes a Unicode fraction slash, but 2027.7 makes it an error. '_' is
    chosen over '-' because ``sanitize()`` maps both '/' and '_' to '_', so the
    computed object_id (and therefore the Home Assistant entity) is unchanged.
    """
    return name.replace("/", "_")


def _validate_preset(config):
    device_type = config["device_type"]
    if device_type not in _device_types:
        raise cv.Invalid(
            f"Device type '{device_type}' is not a known TopTronic device type"
        )
    if not (PRESETS_DIR / device_type).is_dir():
        available = (
            sorted(d.name for d in PRESETS_DIR.iterdir() if d.is_dir())
            if PRESETS_DIR.is_dir()
            else []
        )
        raise cv.Invalid(
            f"No preset directory found for device type '{device_type}'. "
            f"Available presets: {', '.join(available)}"
        )
    return config


def _validate_hub_uniqueness(config):
    """Reject two hubs polling the same device on the same CAN bus.

    A duplicate ``(canbus_id, device_type, device_addr)`` is the same physical
    device: no name prefix can disambiguate it and it would double-poll the bus.
    ``CORE.config`` holds the raw hub entries, so normalise before counting (the
    validator receives a validated *copy*, hence ``count > 1`` rather than an
    object-identity comparison).
    """
    hubs = _hub_entries()
    identity = _hub_identity(config)
    if sum(1 for h in hubs if _hub_identity(h) == identity) > 1:
        bus, device_type, addr = identity
        raise cv.Invalid(
            f"Duplicate toptronic hub for {device_type} address {addr} on CAN bus "
            f"'{bus}': each device must be polled by exactly one hub. Use a "
            f"distinct device_addr, or name_prefix if the two buses really differ."
        )
    return config


def _validate_options_values_lengths(config):
    """Validate that 'options' and 'values' lists have matching lengths (select/text_sensor).

    Per instructions.md §7.3 these MUST match; a mismatch would otherwise surface as a
    bare IndexError during code generation instead of a clean validation error.
    """
    if len(config[CONF_OPTIONS]) != len(config[CONF_VALUES]):
        raise cv.Invalid(
            f"'options' length ({len(config[CONF_OPTIONS])}) must match "
            f"'values' length ({len(config[CONF_VALUES])})"
        )
    return config


CONFIG_SCHEMA_BASE = cv.Schema(
    {
        cv.Required(CONF_FUNCTION_GROUP): cv.uint8_t,
        cv.Required(CONF_FUNCTION_NUMBER): cv.uint8_t,
        cv.Required(CONF_DATAPOINT): cv.uint16_t,
    }
)


def config_schema_polling(update_interval: str = "30s"):
    """Return CONFIG_SCHEMA_BASE extended with a configurable polling interval.

    Read-only entities (sensor/text_sensor) poll the bus via their inherited
    PollingComponent update() at this interval. Write-only entities (number,
    select, button) use plain CONFIG_SCHEMA_BASE instead — they have no update
    callback, so polling them every interval would only wake the scheduler for a
    no-op. Without the polling schema, register_component() does not emit
    set_update_interval(), leaving the PollingComponent default SCHEDULER_DONT_RUN.
    """
    return CONFIG_SCHEMA_BASE.extend(cv.polling_component_schema(update_interval))


CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(TopTronicComponent),
            cv.GenerateID(CONF_CANBUS_ID): cv.use_id(CanbusComponent),
            cv.Required("device_type"): cv.one_of(
                *[t.name for t in DeviceType], upper=True
            ),
            cv.Required(CONF_DEVICE_ADDR): cv.uint8_t,
            cv.Optional(CONF_LANGUAGE, default="en"): cv.one_of(*LANGS, lower=True),
            cv.Optional(CONF_NAME_PREFIX): cv.string,
            cv.Optional(
                CONF_BOOT_REFRESH_DELAY, default="30s"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_MAX_PENDING_MESSAGES, default=32): cv.int_range(
                min=1, max=512
            ),
            cv.Optional(
                CONF_MAX_PENDING_AGE, default="5000ms"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(
                CONF_CLEANUP_INTERVAL, default="5000ms"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_MAX_REFRESH_PER_LOOP, default=8): cv.int_range(
                min=1, max=255
            ),
            cv.Optional(CONF_MAX_FRAMES_PER_MESSAGE, default=8): cv.int_range(
                min=3, max=31
            ),
            cv.Optional(
                CONF_REFRESH_GAP_MS, default="50ms"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(CONF_MAX_REFRESH_RETRIES, default=1): cv.int_range(
                min=0, max=10
            ),
            cv.Optional(
                CONF_REFRESH_RETRY_INTERVAL_MS, default="200ms"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(
                CONF_WRITE_MIN_INTERVAL, default="2s"
            ): cv.positive_time_period_milliseconds,
            cv.Optional(
                CONF_REJECT_WRITES_BEFORE_READ, default=True
            ): cv.boolean,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    _validate_preset,
    _validate_hub_uniqueness,
)


def _load_entities(device_type: str, language: str):
    entities = []
    for kind in ("sensors", "inputs", "buttons"):
        path = PRESETS_DIR / device_type / f"{kind}_{language}.yaml"
        if not path.exists():
            continue
        # Presets are loaded with ESPHome's own YAML loader (not plain
        # yaml.safe_load) so scalar strings carry the ESPHomeDataBase/esp_range
        # metadata that cv.lambda_'s validator requires when wrapping a lambda
        # value; otherwise it fails with "'str' object has no attribute
        # 'esp_range'" for any preset entity using a `lambda:` filter.
        data = yaml_util.load_yaml(path, clear_secrets=False) or {}
        for platform_name, entries in data.items():
            entities.extend((platform_name, dict(entry)) for entry in entries or [])
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
        if (
            obj.is_declaration
            and isinstance(obj.type, cg.MockObjClass)
            and obj.type.inherits_from(Component)
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

    prefix = _resolve_hub_prefix(config)
    # Qualifier for colliding preset ids: the hub's device type + address, plus the
    # CAN bus id when two hubs share both (only the bus tells them apart — matching
    # the name prefix). Computed once per hub.
    identity = _hub_identity(config)  # (bus_id, device_type, device_addr)
    identities = [_hub_identity(h) for h in _hub_entries()]
    id_qualifier = f"{identity[1]}_{identity[2]}"
    if sum(1 for i in identities if i[1] == identity[1] and i[2] == identity[2]) > 1:
        id_qualifier = f"{id_qualifier}_{identity[0]}"
    used_ids = _shared_used_ids()
    for platform_name, entity_conf in _load_entities(
        config["device_type"], config[CONF_LANGUAGE]
    ):
        if platform_name not in platforms:
            raise cv.Invalid(
                f"Unsupported platform '{platform_name}' in toptronic preset"
            )
        entity_conf.pop("platform", None)
        entity_conf.pop("device_type", None)
        entity_conf.pop(CONF_DEVICE_ADDR, None)
        hub_ref = config[CONF_ID].copy()
        hub_ref.is_declaration = False
        entity_conf[CONF_TOPTRONIC_ID] = hub_ref

        # Hubs of the same device type load the same preset files, which carry
        # hard-coded `id:`s (e.g. HV_50_0_40651). The first hub keeps them
        # verbatim so existing lambdas keep working; only an actual collision is
        # prefixed with `id_qualifier` (type + address, plus the bus id when two
        # hubs also share the address, so 3+ buses stay unique). `used_ids` only
        # ever holds toptronic-generated ids, so this never renames an entity
        # because of an unrelated user id.
        entity_id = entity_conf.get(CONF_ID)
        if isinstance(entity_id, str) and entity_id in used_ids:
            entity_conf[CONF_ID] = f"{id_qualifier}_{entity_id}"

        # Unique build-wide (see _resolve_hub_prefix) and free of '/' (ESPHome's
        # reserved URL path separator — see _sanitize_entity_name). The prefix is
        # composed first so an explicit name_prefix is sanitized too.
        name = entity_conf.get(CONF_NAME)
        if name:
            if prefix:
                name = f"{prefix} {name}"
            entity_conf[CONF_NAME] = _sanitize_entity_name(name)

        schema, codegen = platforms[platform_name]
        validated = schema(entity_conf)
        _resolve_ids(validated, used_ids)
        await codegen(validated)


_REFRESH_BUTTON_KEY = "toptronic_refresh_button_generated"


async def _generate_refresh_button(hub_var):
    """Emit a single build-wide 'Refresh all' button (once, on the first hub).

    The on-press action is handled in C++ (TopTronicRefreshButton::press_action()
    -> refresh_all()), so no lambda or hardcoded hub id is needed in YAML. The
    button id is auto-generated from the component namespace.
    """
    if CORE.data.setdefault(_REFRESH_BUTTON_KEY, False):
        return
    CORE.data[_REFRESH_BUTTON_KEY] = True

    friendly = (CORE.config.get(CONF_SUBSTITUTIONS, {}) or {}).get(
        "friendly_name", ""
    ) or ""
    name = f"{friendly} Refresh all" if friendly else "Refresh all"

    cfg = button_platform.button_schema(TopTronicRefreshButton)(
        {
            CONF_NAME: name,
            CONF_ICON: "mdi:refresh",
            CONF_ENTITY_CATEGORY: "config",
        }
    )
    _resolve_ids(cfg, _shared_used_ids())
    var = cg.new_Pvariable(cfg[CONF_ID])
    cg.add(var.set_parent(hub_var))
    await button_platform.register_button(var, cfg)
    await cg.register_component(var, cfg)


async def to_code(config):
    cbus = await cg.get_variable(config[CONF_CANBUS_ID])
    var = cg.new_Pvariable(config[CONF_ID], cbus)
    await cg.register_component(var, config)

    device_type = get_device_type(config["device_type"])
    cg.add(var.set_device_type(device_type))
    cg.add(var.set_device_addr(config[CONF_DEVICE_ADDR]))
    cg.add(var.set_boot_refresh_delay(config[CONF_BOOT_REFRESH_DELAY]))
    cg.add(var.set_max_pending_messages(config[CONF_MAX_PENDING_MESSAGES]))
    cg.add(var.set_max_pending_age_ms(config[CONF_MAX_PENDING_AGE]))
    cg.add(var.set_cleanup_interval_ms(config[CONF_CLEANUP_INTERVAL]))
    cg.add(var.set_max_refresh_per_loop(config[CONF_MAX_REFRESH_PER_LOOP]))
    cg.add(var.set_max_frames_per_message(config[CONF_MAX_FRAMES_PER_MESSAGE]))
    cg.add(var.set_refresh_gap_ms(config[CONF_REFRESH_GAP_MS]))
    cg.add(var.set_max_refresh_retries(config[CONF_MAX_REFRESH_RETRIES]))
    cg.add(var.set_refresh_retry_interval_ms(config[CONF_REFRESH_RETRY_INTERVAL_MS]))
    cg.add(var.set_write_min_interval(config[CONF_WRITE_MIN_INTERVAL]))
    cg.add(var.set_reject_writes_before_read(config[CONF_REJECT_WRITES_BEFORE_READ]))

    await _generate_entities(var, config)

    await _generate_refresh_button(var)

    # Critical wiring (update callbacks, command queue, pump, boot-refresh gate)
    # must not depend on ESPHome invoking setup(): ESPHOME_COMPONENT_COUNT is
    # computed from CORE.component_ids before preset entities are registered, so
    # a hub can be silently dropped from components_ and setup() never runs.
    # Config-phase statements always run for every hub.
    cg.add(var.configure_hub())
