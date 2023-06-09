import openpyxl
import yaml
import os

computed_devices = ['HV'] #['FV', 'GLT', 'GW', 'HKW', 'HV','MWA', 'PS','SOL', 'WEZ']

wb = openpyxl.load_workbook(filename='TTE-GW-Modbus-datapoints.xlsx', read_only=True)

ret_sensor = []

def parse_and_merge(ws, ret_sensor):
    header_found = False
    dpid_set = set()  # Set to store unique dpids
    for row in ws.iter_rows(values_only=True):
        if not header_found:
            header_found = True
            continue
        dpid = []
        all_data = {}  # Dictionary to store all data
        for i, cell_value in enumerate(row):
            if i >= 3 and i <= 5:
                dpid.append(str(cell_value))
            elif i == 1:
                dpid.append(cell_value)
                all_data['device'] = cell_value
            elif i == 6:  # DatapointName
                all_data['descr'] = cell_value
            elif i == 8:  # TypeName
                all_data['type'] = cell_value
            elif i == 9:  # Decimal
                all_data['accuracy_decimals'] = cell_value
            elif i == 10:  # FunctionGroup name
                all_data['function_group'] = cell_value
            elif i == 11:  # Function name
                all_data['function_name'] = cell_value
            elif i == 12:  # Steps
                all_data['steps'] = cell_value
            elif i == 13:  # Min. value
                all_data['min'] = cell_value
            elif i == 14:  # Max. value
                all_data['max'] = cell_value
            elif i == 15:  # Writable
                all_data['writable'] = True if cell_value and cell_value.lower() == 'yes' else False
            elif i == 16:  # Unit
                all_data['unit_of_measurement'] = cell_value
            elif i == 17:  # Comment
                all_data['comment'] = cell_value

        dpid = "-".join(dpid)  # identifier like "HV-50-0-37600"

        #if dpid not in dpid_set: ## for all devices
        if dpid not in dpid_set and all_data.get('device') in computed_devices : # list your devices : in ['HV', 'SOL', 'HKW']:
            sensor = {
                'platform': 'template',
                'id': dpid,
                'name': "${" + dpid + "}",
                'accuracy_decimals': all_data.get('accuracy_decimals', 0)
            }
            
            unit_of_measurement = all_data.get('unit_of_measurement')
            if unit_of_measurement != 0:
                sensor['unit_of_measurement'] = unit_of_measurement

            type_name = all_data.get('type')
            if type_name == 'S16':
                sensor['filters'] = [{'multiply': 0.1}]
            
            datapoint_name = all_data.get('descr')
            if datapoint_name and 'humidity' in datapoint_name.lower():
                sensor['icon'] = "mdi:water-percent"
                sensor['device_class'] = "humidity"
                sensor['state_class'] = "measurement"       

            if unit_of_measurement in ['°C', '°F', 'K']:
                sensor['icon'] = "mdi:temperature"
                sensor['device_class'] = "temperature"
                sensor['state_class'] = "measurement"                
            
            ret_sensor.append(sensor)
            dpid_set.add(dpid)

parse_and_merge(wb.worksheets[1], ret_sensor)  # English only

with open('sensor.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_sensor, f, encoding="utf-8", sort_keys=False)
