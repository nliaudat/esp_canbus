import pathlib
from xls_parser import parse_datapoints, Filter, dump_inputs, dump_sensors, translate, Datapoint
import argparse
import os
import sys
import openpyxl
from openpyxl import Workbook
from typing import Callable, Optional
import re

PatchFunc = Callable[[list[Datapoint], str], None]

class Preset():

    def __init__(self, id: str, filter: Filter | list[Datapoint], before_translate: Optional[PatchFunc] = None, before_dump: Optional[PatchFunc] = None):
        self.id = id
        self.filter = filter
        self.before_translate = before_translate
        self.before_dump = before_dump

    def generate(self, wb: Workbook, out_dir: pathlib.Path):
        locales = ['de', 'en', 'fr', 'it']
        
        for locale in locales:
            print(f"Generating {self.id} {locale} ...")
            
            datapoints = self.filter if type(self.filter) == list else self._get_datapoints(wb, locale)

            if self.before_dump:
                self.before_dump(datapoints, locale)
            
            for dp in datapoints:
                if dp.type_name in ["U32", "S32"]:
                    dp.name = re.sub(r'( low| high)$', "", dp.name) # for HV
                    dp.name = re.sub(r'(_low|_high)$', "", dp.name) # for WEZ

            os.makedirs(out_dir.joinpath(self.id), exist_ok=True)

            dump_sensors(datapoints, out_dir.joinpath(self.id, f'sensors_{locale}.yaml'))
            dump_inputs(datapoints, out_dir.joinpath(self.id, f'inputs_{locale}.yaml'))

    def _get_datapoints(self, wb: Workbook, locale: str = 'en'):
        datapoints = parse_datapoints(wb, self.filter)

        if self.before_translate:
            self.before_translate(datapoints, locale)
        
        translate(wb, datapoints, locale)
        return datapoints

def _translate(datapoints: list[Datapoint], locale: str, translations: dict[str, dict[str, str]]):
    t = translations[locale]
    
    for dp in datapoints:
        dp.name = t.get(dp.get_id(), dp.name)

def hv_before_translate(datapoints: list[Datapoint], _: str):
    # Patch type of "Status vent. regulation" from U8 to LIST
    for dp in  datapoints:
        if dp.datapoint == 39652:
            dp.type_name = 'LIST'

# Status-word maps (ported from the independent HoxPi project, MIT license):
# human-readable labels for numeric status datapoints that Hoval does not type
# as LIST.  German is the master map; English mirrors it; fr/it fall back to
# English.  Keys are (function_group, function_number, datapoint).
# Insertion order = value order (into_text_sensor/into_select emit values in
# dict order, so keys MUST stay ascending).
_ST_HC = {
    'de': {0: 'Abgeschaltet', 1: 'Heizen normal', 2: 'Heizen Komfort', 3: 'Heizen Eco',
           4: 'Frostschutz', 7: 'Ferien', 8: 'Party', 9: 'Kühlen normal',
           10: 'Kühlen Komfort', 11: 'Kühlen Eco', 12: 'STÖRUNG', 13: 'Handbetrieb',
           14: 'Schutz-Kühlbetrieb', 22: 'Kühlen extern/konstant',
           23: 'Heizen extern/konstant', 26: 'SmartGrid-Vorzug'},
    'en': {0: 'Off', 1: 'Heating normal', 2: 'Heating comfort', 3: 'Heating eco',
           4: 'Frost protection', 7: 'Holiday', 8: 'Party', 9: 'Cooling normal',
           10: 'Cooling comfort', 11: 'Cooling eco', 12: 'FAULT', 13: 'Manual mode',
           14: 'Protection cooling', 22: 'Cooling external/constant',
           23: 'Heating external/constant', 26: 'SmartGrid priority'},
}
_ST_DHW = {
    'de': {0: 'Aus', 1: 'Laden normal', 2: 'Laden Komfort', 5: 'STÖRUNG',
           6: 'Zapfung', 8: 'Laden reduziert', 12: 'SmartGrid-Vorzug',
           13: 'SmartGrid-Zwang'},
    'en': {0: 'Off', 1: 'Charging normal', 2: 'Charging comfort', 5: 'FAULT',
           6: 'Draw-off', 8: 'Charging reduced', 12: 'SmartGrid priority',
           13: 'SmartGrid forced'},
}
_ST_HP = {
    'de': {0: 'Aus', 1: 'Heizen', 2: 'Aktiv-Kühlen', 3: 'Sperre',
           4: 'WW-Laden', 5: 'Frostschutz', 6: 'WEZ-Temp zu tief', 7: 'VL zu hoch',
           8: 'Abtauen', 9: 'Passiv-Kühlen', 11: 'Hochdruck-Störung',
           12: 'Niederdruck-Störung', 16: 'Wiederanlauf', 17: 'EVU-Sperre',
           18: 'Vorlaufzeit', 19: 'Nachlaufzeit', 44: 'MOP',
           49: 'Abtauung erfolglos', 51: 'Kondensatorpumpe', 55: 'Inverter-Störung',
           97: 'Ölvorwärmung', 98: 'Kaltstart'},
    'en': {0: 'Off', 1: 'Heating', 2: 'Active cooling', 3: 'Lockout',
           4: 'DHW charging', 5: 'Frost protection', 6: 'WEZ temp too low',
           7: 'Flow too high', 8: 'Defrost', 9: 'Passive cooling',
           11: 'High pressure fault', 12: 'Low pressure fault', 16: 'Restart delay',
           17: 'Utility block', 18: 'Pre-run', 19: 'After-run', 44: 'MOP',
           49: 'Defrost failed', 51: 'Condensate pump', 55: 'Inverter fault',
           97: 'Oil preheat', 98: 'Cold start'},
}
_ST_SG = {
    'de': {0: 'Normal', 1: 'Vorzugbetrieb', 2: 'Gesperrt', 3: 'Abnahmezwang',
           255: 'inaktiv'},
    'en': {0: 'Normal', 1: 'Priority operation', 2: 'Locked',
           3: 'Forced demand', 255: 'inactive'},
}
_ST_UKA = {
    'de': {0: 'zu', 1: 'offen'},
    'en': {0: 'closed', 1: 'open'},
}
# Smart-Grid registers Hoval types as U8 but HoxPi exposes as a labelled select.
_SG_BUS = {
    'de': {0: 'Normal', 1: 'Vorzugbetrieb', 2: 'Gesperrt', 3: 'Abnahmezwang'},
    'en': {0: 'Normal', 1: 'Priority operation', 2: 'Locked',
           3: 'Forced demand'},
}
_SG_TRG = {
    'de': {0: 'Aus', 1: 'Eingangskontakte', 2: 'Systembus',
           3: 'Leistung gedämpft'},
    'en': {0: 'Off', 1: 'Input contacts', 2: 'System bus', 3: 'Power damped'},
}
_TEXT_OVERRIDES = {
    (1, 0, 2051): _ST_HC,      # Status Heizkreisregelung HK1
    (1, 1, 2051): _ST_HC,      # Status Heizkreisregelung HK2
    (2, 0, 2052): _ST_DHW,     # Status Warmwasserregelung
    (60, 254, 34): _ST_HP,     # Betriebsstatus
    (0, 0, 21090): _ST_SG,     # Status Smart Grid
    (3, 0, 22024): _ST_UKA,    # Status Kühlventil aktiv UKA
    (0, 0, 38012): _SG_BUS,    # Smart Grid über Systembus -> labelled select
    (0, 0, 38013): _SG_TRG,    # Auslöser Smart Grid Funktion -> labelled select
}


def wez_before_dump(datapoints: list[Datapoint], locale: str):
    rows = {
        1379, 1380, 1381, # Heating operation choice
        1382, 1384, 1386, # normal room temp.
        1383, 1385, 1387, # conservation romm temp.
        1402, 1403,       # Status Heizkreisregelung HK1/HK2 (same name)
        1414, 1415, 1416, # actual flow temperature
        26692, 26693, 26694, # SG-Offset Raum-Soll Heizen HK1-3 (same name)
        26695, 26696,     # SG-Offset Raum-Soll Kühlen HK1-2 (same name)
    }

    # add heat circle number to duplicated names, and turn numeric status
    # datapoints into LIST (text_sensor / select) using the HoxPi maps
    for dp in datapoints:
        if dp.row in rows:
            dp.name = f'{dp.name} ({dp.function_number+1})'
        items = _TEXT_OVERRIDES.get((dp.function_group, dp.function_number, dp.datapoint))
        if items:
            dp.type_name = 'LIST'
            dp.text = items['de'] if locale == 'de' else items['en']

def bd_before_dump(datapoints: list[Datapoint], locale: str):
    translations = {
        'en': {
            'BM_83_0_0': 'Room actual'
        },
        'de': {
            'BM_83_0_0': 'Raum-Ist'
        },
        'fr': {
            'BM_83_0_0': 'Valeur réelle pièce'
        },
        'it': {
            'BM_83_0_0': 'Ambiente-effettivo'
        }
    }
    _translate(datapoints, locale, translations)

def _strip_suffixes(datapoints: list[Datapoint]):
    # U32/S32 values are listed as _high/_low rows in the workbook; both halves
    # share the same datapoint id, so a preset keeps a single 32-bit entity.
    for dp in datapoints:
        if dp.type_name in ["U32", "S32"]:
            dp.name = re.sub(r'( low| high)$', "", dp.name) # for HV
            dp.name = re.sub(r'(_low|_high)$', "", dp.name) # for WEZ

def _disambiguate_duplicates(datapoints: list[Datapoint]):
    # The same datapoint is exposed once per heating circuit / DHW circuit /
    # storage tank / heat meter.  Append (n) so entity names stay unique.
    from collections import Counter
    counts = Counter(dp.name for dp in datapoints)
    for dp in datapoints:
        if counts[dp.name] > 1:
            dp.name = f'{dp.name} ({dp.function_number+1})'

def _apply_text_overrides(datapoints: list[Datapoint], locale: str, overrides):
    for dp in datapoints:
        items = overrides.get((dp.function_group, dp.function_number, dp.datapoint))
        if items:
            dp.type_name = 'LIST'
            dp.text = items['de'] if locale == 'de' else items['en']

# Status-word maps for the FW (HK1..5 / WW1..5) and HKW (HK1..3) controllers.
# Same HoxPi maps as the WEZ _TEXT_OVERRIDES above, extended to the extra
# function numbers those devices expose.
_HVAC_TEXT_OVERRIDES = {
    (1, 0, 2051): _ST_HC,  # Status Heizkreisregelung
    (1, 1, 2051): _ST_HC,
    (1, 2, 2051): _ST_HC,
    (1, 3, 2051): _ST_HC,
    (1, 4, 2051): _ST_HC,
    (2, 0, 2052): _ST_DHW, # Status Warmwasserregelung
    (2, 1, 2052): _ST_DHW,
    (2, 2, 2052): _ST_DHW,
    (2, 3, 2052): _ST_DHW,
    (2, 4, 2052): _ST_DHW,
}

def hvac_before_dump(datapoints: list[Datapoint], locale: str):
    # FW / HK (HKW): heating circuits + DHW, status words as text sensors
    _strip_suffixes(datapoints)
    _disambiguate_duplicates(datapoints)
    _apply_text_overrides(datapoints, locale, _HVAC_TEXT_OVERRIDES)

def numbered_before_dump(datapoints: list[Datapoint], locale: str):
    # SOL / MWA: duplicated names across collectors, storage tanks or meters
    _strip_suffixes(datapoints)
    _disambiguate_duplicates(datapoints)

def mbus_rows(wb, unit_name: str, unit_id: int, dp_ids: set[int]) -> list[int]:
    """Return the Excel row numbers of one unit instance's M-Bus heat meters
    (function group 20) that expose any of the given datapoint ids.

    U32/S32 values appear as two rows (_high/_low halves sharing the same
    datapoint id); only the first row of each pair is kept so the preset emits
    a single 32-bit entity.
    """
    rows = []
    seen = set()
    for r in wb.worksheets[1].iter_rows(min_row=2):
        if r[1].value != unit_name or r[2].value != unit_id or r[3].value != 20:
            continue
        key = (r[4].value, r[5].value)  # (function_number, datapoint)
        if r[5].value not in dp_ids or key in seen:
            continue
        seen.add(key)
        rows.append(r[1].row)
    return rows

# --- curated datapoint rows for the remaining Hoval devices ------------------
# One row per datapoint: for U32/S32 values the workbook lists a _high/_low
# pair sharing the same datapoint id, so only the _low row is kept here.
_GW_ROWS = [
    15846, # AFG1 - system outdoor sensor 1
    15847, # AFG2 - system outdoor sensor 2
    15848, # Expected global radiation
    18967, # Unix time (U32 low)
    28216, # PV active power (U32 low)
]
_GLT_ROWS = [
    16917, # Temperature requirement heating
    16918, # Temperature requirement cooling
    16919, # Temperature requirement DHW
    16920, # Power setpoint heating
    16921, # Power setpoint cooling
    16922, # Power setpoint DHW
    16923, 16924, 16925, # Info 1-3 0-10V
    18566, 18567, 18568, 18569, 18570, # Info 1-5
]
_PS_ROWS = [
    15928, # Status buffer
    15929, # Buffer setpoint
    15930, # Buffer PF/KPF2 actual
    15931, # Buffer PF2/KPF actual
    27975, # Smart-Grid offset buffer setpoint heating
    27976, # Smart-Grid offset buffer setpoint cooling
]
_SOL_ROWS = [
    2, 3, # TKO1 / TKO2 collector temp.
    10, 5, # Total collector yield (S32) collector 1 / 2
    11, 6, # Current collector power collector 1 / 2
    8, 7, # Solar pump operating hours collector 1 / 2
    80, 84, # Solar flow rate
    81, 85, # Collector flow temp.
    82, 86, # Collector return temp.
    83, 87, # Solar pump speed
    70, 71, # Status solar controller
    28247, 28248, # Current collector setpoint
    28252, 28253, # Partial collector yield
    72, 74, 76, 78, # Storage tank bottom temp.
    73, 75, 77, 79, # Storage tank top temp.
    28231, 28232, 28233, 28234, # Storage priority
    28235, 28236, 28237, 28238, # Storage max temp.
    28239, 28240, 28241, 28242, # Storage protection temp.
    28243, 28244, 28245, 28246, # Storage set temp.
    28249, 28250, 28251, # Diverter valve state
]
# HKW in the workbook, HK in the component (DeviceType.HK = 256)
_HK_ROWS = [
    3506, # AF1 - outdoor sensor 1
    3535, # AF2 - outdoor sensor 2
    19038, # FAV flow setpoint temp.
    19054, # FAV flow actual temp.
    19070, # AVP pump
    19086, # YAV mixer
    # heating circuits 1..3
    3507, 3508, 3509, # Heating operation choice
    3510, 3512, 3514, # Normal room temp.
    3511, 3513, 3515, # Eco room temp.
    3516, 3517, 3518, # Room setpoint
    3519, 3520, 3521, # Manual-mode setpoint temp.
    3522, 3523, 3524, # Flow setpoint, const. demand heating
    22951, 22952, 22953, # Flow setpoint, const. demand cooling
    3536, 3537, 3538, # Room actual
    3539, 3540, 3541, # Flow actual
    19102, 19103, 19104, # Return actual
    19150, 19151, 19152, # Mixer
    19198, 19199, 19200, # Pump
    3531, 3532, 3533, # Status heating circuit
    22647, 22648, 22649, # Flow setpoint
    # DHW 1
    3525, # DHW operation choice
    3526, # Normal DHW temp.
    3527, # Eco DHW temp.
    3528, # DHW setpoint
    3529, # DHW actual
    3530, # DHW loading pump
    3534, # Status DHW
    19247, # Circulation circuit temp.
    19248, # Circulation pump
]
_FW_ROWS = [
    5010, # AF1 - outdoor sensor 1
    5066, # AF2 - outdoor sensor 2
    21929, # Return limit active
    21930, # Power limit active
    21931, # Station valve position
    21932, # FAV flow setpoint temp.
    21933, # FAV flow actual temp.
    21934, # AVP pump
    21935, # YAV pump
    21936, # Buffer level
    21937, # Pressure
    5180, # Operating hours (U32 low)
    # heating circuits 1..5
    5011, 5012, 5013, 5014, 5015, # Heating operation choice
    5016, 5018, 5020, 5022, 5024, # Normal room temp.
    5017, 5019, 5021, 5023, 5025, # Eco room temp.
    5026, 5027, 5028, 5029, 5030, # Room setpoint
    5056, 5057, 5058, 5059, 5060, # Status heating circuit
    5067, 5068, 5069, 5070, 5071, # Room actual
    5072, 5073, 5074, 5075, 5076, # Flow actual
    21938, 21941, 21944, 21947, 21950, # Mixer
    21939, 21942, 21945, 21948, 21951, # Pump
    21940, 21943, 21946, 21949, 21952, # Flow setpoint
    29671, 29672, 29673, 29674, 29675, # Flow setpoint, const. demand
    # DHW 1..5
    5031, 5032, 5033, 5034, 5035, # DHW operation choice
    5036, 5038, 5040, 5042, 5044, # Normal DHW temp.
    5037, 5039, 5041, 5043, 5045, # Eco DHW temp.
    5046, 5048, 5050, 5052, 5054, # DHW setpoint
    5047, 5049, 5051, 5053, 5055, # DHW actual
    5061, 5062, 5063, 5064, 5065, # Status DHW
    21953, 21957, 21961, 21965, 21969, # DHW loading pump 1
    21955, 21959, 21963, 21967, 21971, # Circulation circuit temp.
    21956, 21960, 21964, 21968, 21972, # Circulation pump
]
_MWA_MBUS_DPS = {0, 1, 2, 3, 4, 5, 6, 7, 11, 12, 13}
_FW_MBUS_DPS = {0, 1, 2, 3, 4, 5, 6, 8, 50, 51}

if __name__ == "__main__":
    presets = [
        Preset('WEZ', Filter(rows=[
            1378, # AF1 - outdoor sensor 1
            1379, 1380, 1381, # Heating operation choice
            1382, 1384, 1386, # normal room temp.
            1383, 1385, 1387, # conservation romm temp.
            1414, 1415, 1416, # actual flow temperature
            1397, # hot water operation choice
            1398, # Normal hot water temp.
            1399, # Conservation hot water temp.
            1400, # Hot water setpoint
            1401, # hot water temp.
            1402, 1403, # Status Heizkreisregelung HK1/HK2 (text_sensor)
            1405, # Status Warmwasserregelung (text_sensor)
            1437, # WEZ output
            1441, # Betriebsstatus (text_sensor)
            1462, # Betriebswahl Wärmeerzeuger (select)
            19034, # Status Kühlventil aktiv UKA (text_sensor)
            24778, # Electrical energy WEZ MWh
            26649, # Heat quantity heating
            26653, # Heat quantity DHW
            26673, # Smart-Grid (Offset) WW-Sollwert
            26692, 26693, 26694, # SmartGrid Offset Raum-Sollw. Heizen HK1-3
            26695, 26696, # SmartGrid Offset Raum-Sollw. Kühlen HK1-2
            26701, # Status Smart Grid (text_sensor)
            26709, # Smart Grid über Systembus (select)
            26710, # Auslöser Smart Grid Funktion (select)
        ]), before_dump=wez_before_dump),
        ## filter the row number, not the datapoint :  based on UniName=HV, UnitId=520
        Preset('HV', Filter(rows=[ 
            22786, # Op. choice ventilation
            22787, # Normal ventilation modulation
            22788, # Eco ventilation modulation
            22789, # Ventilation modulation
            22790, # Humidity set value
            22791, # Humidity extract air
            # 22792, # VOC extract air # not relevant
            # 22793, # VOC outdoor air # not relevant
            # 22794, # Air quality control # not relevant
            22795, # Status vent regulation
            22796, # Outside air temp.            
            22797, # Extract air temp.
            22798, # Fan exhaust air set   
            # 23314, # Active error 1 # testing
            # 23323, # Active error 2
            # 23332, # Active error 3
            # 23341, # Active error 4
            # 23350, # Active error 5
            28099, # Maint.ctr.value message maint. (op. wks)
            # 28101, # Rem. run time maint. counter (op. weeks) # not relevant
            28110, # Cleaning count value message cleaning (operating weeks)
        ]), hv_before_translate),
        Preset('BM', [
            Datapoint(
                row=0,
                name='Room actual',
                unit_name='BM',
                unit_id=1,
                function_group=83,
                function_number=0,
                datapoint=0,
                type_name='S16',
                decimal=1,
                steps=1,
                min=0,
                max=0,
                writable=False,
                unit='°C',
                text={},
            ),
        ], before_dump=bd_before_dump),
    ]

    parser = argparse.ArgumentParser(
        prog='Generate Presets',
        description='Generates sensors and inputs for Hoval devices',
    )

    parser.add_argument('out_dir')
    parser.add_argument('--xlsx', default=None,
                        help='path to the Hoval datapoint workbook '
                             '(default: hoval_data_processing/TTE-GW-Modbus-datapoints.xlsx)')
    parser.add_argument('--only', nargs='*', default=None,
                        help='generate only the given preset ids (e.g. FW HK MWA)')
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)

    path = pathlib.Path(args.xlsx) if args.xlsx else pathlib.Path(__file__).parent.joinpath('TTE-GW-Modbus-datapoints.xlsx')
    if not path.exists():
        print(f'ERROR: Hoval datapoint workbook not found at {path}')
        print('The workbook is copyrighted by Hoval AG and is not shipped with this repo.')
        print('Download it once (see hoval_data_processing/readme.md) or run:')
        print('  python hoval_data_processing/update_datapoints.py --apply')
        sys.exit(1)
    wb = openpyxl.load_workbook(filename=path, read_only=False, data_only=True)

    # Presets for the remaining Hoval devices.  Note the workbook names the
    # heating-circuit unit "HKW"; the component's DeviceType enum uses "HK"
    # (256), so the preset folder is named "HK".
    presets += [
        Preset('GW', Filter(rows=_GW_ROWS)),
        Preset('GLT', Filter(rows=_GLT_ROWS)),
        Preset('PS', Filter(rows=_PS_ROWS)),
        Preset('SOL', Filter(rows=_SOL_ROWS), before_dump=numbered_before_dump),
        Preset('HK', Filter(rows=_HK_ROWS), before_dump=hvac_before_dump),
        Preset('MWA', Filter(rows=mbus_rows(wb, 'MWA', 385, _MWA_MBUS_DPS)),
               before_dump=numbered_before_dump),
        Preset('FW', Filter(rows=_FW_ROWS + mbus_rows(wb, 'FW', 193, _FW_MBUS_DPS)),
               before_dump=hvac_before_dump),
    ]

    for preset in presets:
        if args.only and preset.id not in args.only:
            continue
        preset.generate(wb, out_dir)