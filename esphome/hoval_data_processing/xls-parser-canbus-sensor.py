import openpyxl
#import yaml
import os

computed_devices = ['HV'] #['FV', 'GLT', 'GW', 'HKW', 'HV','MWA', 'PS','SOL', 'WEZ']
datatype = ['U8'] #['U8', 'S16', 'U16', 'LIST']

wb = openpyxl.load_workbook(filename='TTE-GW-Modbus-datapoints.xlsx', read_only=True)

ret_canbus = []

def parse_and_merge(ws, ret_canbus):
    header_found = False
    dpid_set = set()  # Set to store unique dpids
    for row in ws.iter_rows(values_only=True):
        if not header_found:
            header_found = True
            continue
        dpid = []
        all_data = {}  # Dictionary to store all data
        datapointID =""
        for i, cell_value in enumerate(row):
            if i >= 3 and i <= 5:
                dpid.append(str(cell_value))
            elif i == 1:
                dpid.append(cell_value)
                all_data['device'] = cell_value
            if i == 5:  #DatapointId
                all_data['DatapointId'] = cell_value
            # elif i == 6:  # DatapointName
                # all_data['descr'] = cell_value
            elif i == 8:  # TypeName
                all_data['type'] = cell_value
            # elif i == 9:  # Decimal
                # all_data['accuracy_decimals'] = cell_value
            # elif i == 10:  # FunctionGroup name
                # all_data['function_group'] = cell_value
            # elif i == 11:  # Function name
                # all_data['function_name'] = cell_value
            # elif i == 12:  # Steps
                # all_data['steps'] = cell_value
            # elif i == 13:  # Min. value
                # all_data['min'] = cell_value
            # elif i == 14:  # Max. value
                # all_data['max'] = cell_value
            # elif i == 15:  # Writable
                # all_data['writable'] = True if cell_value and cell_value.lower() == 'yes' else False
            elif i == 16:  # Unit
                all_data['unit_of_measurement'] = cell_value
            # elif i == 17:  # Comment
                # all_data['comment'] = cell_value

        dpid = "_".join(dpid)  # identifier like "HV_50_0_37600"

        #if dpid not in dpid_set: ## for all devices
        if dpid not in dpid_set and all_data.get('device') in computed_devices and all_data.get('type') in datatype : 
            #print(all_data)  # Print all_data dictionary to check its contents
            datapointID = all_data.get('DatapointId')
            datapointSubst = '${' + dpid + '}'

            type_name = all_data.get('type')
            if type_name == 'U8':
                output_string = f'''
                    case {datapointID}:
                        id({dpid}).publish_state((uint8_t)x[6]);
                        ESP_LOGD("main", "{datapointSubst} is %f", (uint8_t)x[6]);
                        break;
                '''          
            elif type_name == 'S16':                
                output_string = f'''
                    case {datapointID}:
                        id({dpid}).publish_state((int16_t)(x[6] << 8) + x[7]);
                        ESP_LOGD("main", "{datapointSubst} is %f", (int16_t)(x[6] << 8) + x[7]);
                        break;
                '''       

            
            print(output_string)
            
            ret_canbus.append(output_string)
            dpid_set.add(dpid)

parse_and_merge(wb.worksheets[1], ret_canbus)  # English only

file = open('canbus_sensor.yaml','w')
for line in ret_canbus:
	file.write(line)
file.close()

# with open('canbus_sensor.yaml', 'w', encoding='utf-8') as f:
    # yaml.dump(ret_canbus, f, encoding="utf-8", sort_keys=False)
