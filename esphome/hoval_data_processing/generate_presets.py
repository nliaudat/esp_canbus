import pathlib
from xls_parser import parse_datapoints, Filter, dump_inputs, dump_sensors, translate
import argparse
import os
import openpyxl

if __name__ == "__main__":
    presets = {
        'WEZ': Filter(rows=[
            1378, # outdoor sensor 1
            1379, 1380, 1381, # Heating operation choice
            1382, 1384, 1386, # normal room temp.
            1383, 1385, 1387, # conservation romm temp.
            1414, 1415, 1416, # actual flow temperature
            1401, # hot water temp.
            1437, # WEZ output
        ]),
        'HV': Filter(rows=[
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
        ])
    }

    locales = ['de', 'en', 'fr', 'it']

    parser = argparse.ArgumentParser(
        prog='Generate Presets',
        description='Genertes sensors and inputs for Hoval devices',
    )

    parser.add_argument('out_dir')
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out_dir)
    
    path = pathlib.Path(__file__).parent.joinpath('TTE-GW-Modbus-datapoints.xlsx')
    wb = openpyxl.load_workbook(filename=path, read_only=True)
    
    for locale in locales:
        for device, filter in presets.items():
            print(f"Generating {device} {locale} ...")
            datapoints = parse_datapoints(wb, filter)
            
            # Patch type of "Status vent. regulation" from U8 to LIST
            if device == 'HV':
                for dp in  datapoints:
                    if dp.datapoint == 39652:
                        dp.type_name = 'LIST'
            
            translate(wb, datapoints, locale)

            os.makedirs(out_dir.joinpath(device), exist_ok=True)

            dump_sensors(datapoints, out_dir.joinpath(device, f'sensors_{locale}.yaml'))
            dump_inputs(datapoints, out_dir.joinpath(device, f'inputs_{locale}.yaml'))