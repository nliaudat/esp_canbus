# ESP32 CanBus
made for hoval heat generator, but for all canbus applications
 
## ESP32 CanBus shield

<img src="pcb/hoval_wiring.jpg" width=32%/>  <img src="pcb/3d_view.PNG" width=66%/> 
    
### Functionalities
* Compatible with 1000 or 900 mil width ESP devkit
* Full headers for extending or debug
* The card use a ESP32-WROOM-32D as logics and wifi connection. (You can get a 32U if you want an external antenna)
* The software runs under esphome to be easy to customize and linked with https://www.home-assistant.io 
* Power is taken from CanBus 12V and converted to 3.3v with AMS1117-3.3V (not needed but recommended, if cutting the "3v3V cutout", you can use external power supply)
* SN65HVD230 3.3-V CAN Bus Transceivers

### Fabrication

* PCB can be ordered with chips assembled at JLPCB for 50$ for 5 boards.
* ESP32-WROOM-32D costs approx 3.8$
* Box is 3D printed or fit in a 86x86 electrical box

## Firmware

<img src="esphome/home_assistant.png" />

### Features

* Powered by [ESPHome](https://esphome.io/)
* Webserver enabled at [canbus.local](http://canbus.local/)
* Recognized by [Home Assistant](https://www.home-assistant.io/)

### Installation

1. First install ESPHome: [Manually](https://esphome.io/guides/installing_esphome)/[Docker](https://esphome.io/guides/getting_started_command_line#installation)
2. Enter your Wifi password in `secrets.yaml`
3. Connect your ESP32 via USB to your computer.
4. Run `esphome run config.yaml`

You can add additional data points by modifying `src/sensors.yaml` and `src/inputs.yaml`

## Licence: 
* Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC-BY-NC-SA)
* No commercial use
