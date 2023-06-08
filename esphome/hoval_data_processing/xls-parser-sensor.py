
#### adapted from https://github.com/zittix/Hoval-GW/tte-gw-xls-parser.py

import openpyxl
import yaml
import os

wb = openpyxl.load_workbook(filename = 'TTE-GW-Modbus-datapoints.xlsx', read_only=True)

    
ret_all = {}
ret_sensor = {}

def parse_and_merge(ws, ret_all, ret_sensor):
    header_found = False
    for row in ws.rows:
        if not header_found:
            header_found = True
            continue
        i = 0
        dpid=[]
        descr=None
        all = {
        }
        sensor = {
        }
        for cell in row:
            if i >= 3 and i <=5:
                dpid.append(str(cell.value))
            elif i == 1:
                dpid.append(cell.value)
                all['device'] = cell.value
            elif i == 6: #DatapointName
                all['descr'] = cell.value
                substitutions = cell.value
            elif i == 8: #TypeName
                all['type'] = cell.value
            elif i == 9: #Decimal
                all['accuracy_decimals'] = cell.value
            elif i == 10: #FunctionGroup name
                all['function_group'] = cell.value
            elif i == 11: #Function name
                all['function_name'] = cell.value
            elif i == 12: #Steps
                all['steps'] = cell.value
            elif i == 13: #Min. value
                all['min'] = cell.value
            elif i == 14: #Max. value
                all['max'] = cell.value
            elif i == 15: #Writable
                all['writable'] = True if cell.value and cell.value.lower() == 'Yes' else False
            elif i == 16: #Unit
                all['unit'] = cell.value
            elif i == 17: #Comment
                all['comment'] = cell.value
            # elif i > 17 and cell.value:
                # all['texts'][i - 18] = {lang: cell.value }
            #print(row)
            i+=1
        dpid = "-".join(dpid) #identifier like "HV-50-0-37600"
        
        sensor['id'] = dpid
        sensor['name'] = "${" + dpid +"}"
        sensor['unit_of_measurement'] = all['unit']
        sensor['accuracy_decimals'] = all['accuracy_decimals']

        #ret_sensor[dpid] = sensor # add all, will be curated later
        
        if dpid not in ret_all:  #add only unique
            ret_all[dpid] = all


        if dpid not in ret_sensor:  #add only unique
            ret_sensor[dpid] = sensor
        # else:
            # ret[dpid]['descr'][lang] = all['descr'][lang]
            # ret[dpid]['function_group'][lang] = all['function_group'][lang]
            # ret[dpid]['function_name'][lang] = all['function_name'][lang]
            # ret[dpid]['comment'][lang] = all['comment'][lang]
            # for i in ret[dpid]['texts'].keys():
                # if i in all['texts']:
                    # ret[dpid]['texts'][i][lang] = all['texts'][i][lang]



parse_and_merge( wb.worksheets[1], ret_all, ret_sensor) # english only


with open('sensor.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_sensor, f, encoding="utf-8", indent=4)