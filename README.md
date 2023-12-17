# An ESP32 CanBus shield - made for hoval homevent, but for all canbus applications
 
![alt text](https://github.com/nliaudat/esp_canbus/blob/main/pcb/3d_view.PNG "board")

<img src="https://github.com/nliaudat/esp_canbus/blob/main/pcb/hoval_wiring.jpg" width=50% height=50%>
    
## Functionalities : 
* Compatible with 1000 or 900 mil width ESP devkit
* Full headers for extending or debug
* The card use a ESP32-WROOM-32D as logics and wifi connection. (You can get a 32U if you want an external antenna)
* The software runs under esphome to be easy to customize and linked with https://www.home-assistant.io 
* Power is taken from CanBus 12V and converted to 3.3v with AMS1117-3.3V (not needed but recommended, if cutting the "3v3V cutout", you can use external power supply)
* SN65HVD230 3.3-V CAN Bus Transceivers

## Fabrication : 

* PCB can be ordered with chips assembled at JLPCB for 50$ for 5 boards.
* ESP32-WROOM-32D costs approx 3.8$
* Box is 3D printed or fit in a 86x86 electrical box

## Firmware : (see wiki to configure for your your Hoval model : 'FV', 'GLT', 'GW', 'HKW', 'HV','MWA', 'PS','SOL', 'WEZ')
* Actually runs under Esphome to link hoval homevent devices, but can be general purpose
* (to update ventilation modulation, you must be in "Constant mode")
* Webserver enabled
* Hassio recognized
  <img src="https://github.com/nliaudat/esp_canbus/blob/main/esphome/webserver.PNG" width=75% height=75%>

## Licence: 
* Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC-BY-NC-SA)
* No commercial use
