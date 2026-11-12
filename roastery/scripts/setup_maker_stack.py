#!/usr/bin/env python3
"""Set up the live data stack on the 2027 beta gateway: CoreHistorian,
NorthPlantSim device + program, NorthPlant tags, and (via the roastery
script) RoasterSim + RoastBatch UDT + instance. Uses api27.py (2027 token).
Idempotent-ish. Run with wsvenv python.
"""
import json, sys
from api27m import api

NP_CSV = """TimeInterval,BrowsePath,ValueSource,DataType
0,BoilerSupplyTemp,"sine(170,190,47,true)",Double
0,BoilerReturnTemp,"sine(165,180,59,true)",Double
0,FillerRate,"random(1150,1280,true)",Double
0,SteamHeaderPressure,"sine(95,102,53,true)",Double
0,Line1OEE,"sine(82,93,71,true)",Double
0,AirHandlerTemp,"sine(58,66,43,true)",Double
0,ChillerLoopTemp,"sine(42,48,67,true)",Double
0,PackerInfeedRate,"ramp(0,1200,90,true)",Double
"""

def create_device(name):
    st, out = api('GET', f'/resources/find/com.inductiveautomation.opcua/device/{name}')
    if st == 200:
        print(f'device {name} already exists')
        return out.get('signature')
    body = {'name': name, 'config': {
        'profile': {'type': 'ProgrammableSimulatorDevice'},
        'settings': {'repeat': True, 'timeIntervalRate': 1000,
                     'legacyMode': False}}}
    st, out = api('POST', '/resources/com.inductiveautomation.opcua/device',
                  body=json.dumps([body]))
    print(f'device {name} create HTTP', st)
    if st not in (200, 201):
        print(json.dumps(out)[:600]); sys.exit(1)
    st, out = api('GET', f'/resources/find/com.inductiveautomation.opcua/device/{name}')
    return out.get('signature') if isinstance(out, dict) else None

def upload_csv(name, csv, sig):
    st, out = api('PUT',
                  f'/resources/datafile/com.inductiveautomation.opcua/device/{name}/instructions.csv',
                  body=csv, params={'signature': sig} if sig else None,
                  ctype='application/octet-stream')
    print(f'{name} csv upload HTTP', st, str(out)[:160])

def opc(name, item, device, history=False):
    t = {'name': name, 'tagType': 'AtomicTag', 'valueSource': 'opc',
         'dataType': 'Float8', 'opcServer': 'Ignition OPC UA Server',
         'opcItemPath': f'[{device}]{item}'}
    if history:
        t.update({'historyEnabled': True, 'historyProvider': 'CoreHistorian',
                  'historySampleMode': 'Periodic', 'historySampleRate': 2,
                  'historySampleRateUnits': 'SEC'})
    return t

def main():
    # ---- historian first so tags can reference it
    st, out = api('GET', '/resources/find/com.inductiveautomation.historian/historian-provider/CoreHistorian')
    if st == 200:
        print('historian CoreHistorian already exists')
    else:
        body = {'name': 'CoreHistorian', 'config': {
            'profile': {'type': 'CoreHistorian'},
            'settings': {'partitionInterval': 'WEEK',
                         'dataDeduplication': False,
                         'maintenanceSettings': {
                             'strategy': 'NONE', 'directory': '',
                             'maintenanceAgeUnits': 'MONTH',
                             'maintenanceAge': 6}}}}
        st, out = api('POST', '/resources/com.inductiveautomation.historian/historian-provider',
                      body=json.dumps([body]))
        print('historian create HTTP', st)
        if st not in (200, 201):
            print(json.dumps(out)[:600]); sys.exit(1)

    # ---- NorthPlantSim device + program
    sig = create_device('NorthPlantSim')
    print('NorthPlantSim signature:', sig)
    upload_csv('NorthPlantSim', NP_CSV, sig)

    # ---- NorthPlant tags
    st, out = api('GET', '/tags/export',
                  params={'provider': 'default', 'type': 'json',
                          'path': 'NorthPlant', 'recursive': 'true'})
    if st == 200 and 'BoilerSupplyTemp' in json.dumps(out):
        print('NorthPlant tags already exist, skipping import')
    else:
        folder = {'name': 'NorthPlant', 'tagType': 'Folder', 'tags': [
            opc('BoilerSupplyTemp', 'BoilerSupplyTemp', 'NorthPlantSim', history=True),
            opc('BoilerReturnTemp', 'BoilerReturnTemp', 'NorthPlantSim', history=True),
            opc('FillerRate', 'FillerRate', 'NorthPlantSim'),
            opc('SteamHeaderPressure', 'SteamHeaderPressure', 'NorthPlantSim'),
            opc('Line1OEE', 'Line1OEE', 'NorthPlantSim'),
            opc('AirHandlerTemp', 'AirHandlerTemp', 'NorthPlantSim'),
            opc('ChillerLoopTemp', 'ChillerLoopTemp', 'NorthPlantSim'),
            opc('PackerInfeedRate', 'PackerInfeedRate', 'NorthPlantSim'),
        ]}
        st, out = api('POST', '/tags/import', body=json.dumps(folder),
                      params={'provider': 'default', 'type': 'json',
                              'collisionPolicy': 'Abort'},
                      ctype='application/octet-stream')
        print('NorthPlant import HTTP', st, json.dumps(out)[:300])

if __name__ == '__main__':
    main()
