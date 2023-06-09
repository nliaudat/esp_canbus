import openpyxl
import yaml
import os

computed_devices = ['HV'] #['FV', 'GLT', 'GW', 'HKW', 'HV','MWA', 'PS','SOL', 'WEZ']

wb = openpyxl.load_workbook(filename = 'TTE-GW-Modbus-datapoints.xlsx', read_only=True)

ret_substitutions_DE = {}
ret_substitutions_EN = {}
ret_substitutions_FR = {}
ret_substitutions_IT = {}

def translate(ws, ret_substitutions):
    header_found = False
    for row in ws.rows:
        if not header_found:
            header_found = True
            continue
        i = 0
        dpid=[]
        substitutions = {}
        all_data = {}  # Dictionary to store all data
        for cell in row:
            if i >= 3 and i <=5:
                dpid.append(str(cell.value))
            elif i == 1:
                dpid.append(cell.value)
                all_data['device'] = cell.value
            elif i == 6: #DatapointName
                substitutions = cell.value
            i+=1
        dpid = "-".join(dpid) #identifier like "HV-50-0-37600"


        #if dpid not in ret_substitutions:  #add only unique
        if dpid not in ret_substitutions and all_data.get('device') in computed_devices : 
            ret_substitutions[dpid] = substitutions


translate( wb.worksheets[0], ret_substitutions_DE)
translate( wb.worksheets[1], ret_substitutions_EN)
translate( wb.worksheets[2], ret_substitutions_FR)
translate( wb.worksheets[3], ret_substitutions_IT)

with open('substitutions_DE.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_substitutions_DE, f, encoding="utf-8", indent=4)
    
with open('substitutions_EN.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_substitutions_EN, f, encoding="utf-8", indent=4)
    
with open('substitutions_FR.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_substitutions_FR, f, encoding="utf-8", indent=4)
    
with open('substitutions_EN.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_substitutions_EN, f, encoding="utf-8", indent=4)
    
with open('substitutions_IT.yaml', 'w', encoding='utf-8') as f:
    yaml.dump(ret_substitutions_IT, f, encoding="utf-8", indent=4)

