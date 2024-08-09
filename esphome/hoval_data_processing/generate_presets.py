import pathlib
from xls_parser import parse_datapoints, Filter, dump_inputs, dump_sensors, translate, Datapoint
import argparse
import os
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
            1437, # WEZ output
            24778, # Electrical energy WEZ MWh
            26649, # Heat quantity heating
            26653, # Heat quantity DHW
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
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    
    path = pathlib.Path(__file__).parent.joinpath('TTE-GW-Modbus-datapoints.xlsx')
    wb = openpyxl.load_workbook(filename=path, read_only=True)
    
    for preset in presets:
        preset.generate(wb, out_dir)