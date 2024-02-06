import pathlib
from xls_parser import parse_datapoints, Filter, dump_inputs, dump_sensors, translate, Datapoint
import argparse
import os
import openpyxl
from openpyxl import Workbook
from typing import Callable, Optional

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

def wez_before_dump(datapoints: list[Datapoint], locale: str):
    rows = {
        1379, 1380, 1381, # Heating operation choice
        1382, 1384, 1386, # normal room temp.
        1383, 1385, 1387, # conservation romm temp.
        1414, 1415, 1416, # actual flow temperature
    }

    # add heat circle number
    for dp in datapoints:
        if dp.row in rows:
            dp.name = f'{dp.name} ({dp.function_number+1})'

def bd_before_dump(datapoints: list[Datapoint], locale: str):
    translations = {
        'en': {
            'BD_83_0_0': 'Room actual'
        },
        'de': {
            'BD_83_0_0': 'Raum-Ist'
        },
        'fr': {
            'BD_83_0_0': 'Valeur réelle pièce'
        },
        'it': {
            'BD_83_0_0': 'Ambiente-effettivo'
        }
    }
    _translate(datapoints, locale, translations)
    
if __name__ == "__main__":
    presets = [
        Preset('WEZ', Filter(rows=[
            1378, # outdoor sensor 1
            1379, 1380, 1381, # Heating operation choice
            1382, 1384, 1386, # normal room temp.
            1383, 1385, 1387, # conservation romm temp.
            1414, 1415, 1416, # actual flow temperature
            1397, # hot water operation choice
            1398, # Normal hot water temp.
            1399, # Conservation hot water temp.
            1400, # Hot water setpoint
            1401, # hot water temp.
            1437, # WEZ output
        ]), before_dump=wez_before_dump),
        Preset('HV', Filter(rows=[
            22705, # Outside air temp.
            22700, # Humidity extract air
            22706, # Extract air temp.
            22701, # VOC extract air
            22702, # VOC outdoor air
            22707, # Fan exhaust air set
            22698, # Ventilation modulation
            # 22703, # Air quality control
            22704, # Status vent regulation
            22695, # Op. choice ventilation
            22696, # Normal ventilation modulation
            22697, # Eco ventilation modulation
            22699, # Humidity set value
        ]), hv_before_translate),
        Preset('BD', [
            Datapoint(
                row=0,
                name='Room actual',
                unit_name='BD',
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
        description='Genertes sensors and inputs for Hoval devices',
    )

    parser.add_argument('out_dir')
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    
    path = pathlib.Path(__file__).parent.joinpath('TTE-GW-Modbus-datapoints.xlsx')
    wb = openpyxl.load_workbook(filename=path, read_only=True)
    
    for preset in presets:
        preset.generate(wb, out_dir)