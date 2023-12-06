#include "toptronic.h"
#include "esphome/core/log.h"

#include <sstream>
#include <string>
namespace esphome {
namespace toptronic {

static const char *const TAG = "tt";

uint32_t TopTronicSensor::get_device_id() {
    return (device_type_ << 8) | device_addr_;
}

uint32_t build_can_id(uint8_t message_id, uint8_t priority, uint8_t device_type, uint8_t device_id) {
    return (message_id << 24) | (priority << 16) | (device_type << 8) | device_id;
}

uint32_t TopTronicSensor::get_id() {
    return function_group_
        + (function_number_ << 8)
        + (datapoint_ << 16);
}

template <typename T> 
T bytesToInt(std::vector<uint8_t> value) {
    T a;
    for(int i = 0; i < value.size(); i++) {
        a += value[i] << 8*i;
    }
    return a;
}

float TopTronicSensor::parse_value(std::vector<uint8_t> value) {
    float res = 0.0f;
    switch(type_) {
        case U8:
            {
                res = (float)bytesToInt<uint8_t>(value);
                break;
            }
        case U16:
            {
                res = (float)bytesToInt<uint16_t>(value);
                break;
            }
        case U32:
            {
                res = (float)bytesToInt<uint32_t>(value);
                break;
            }
        case S8:
            {
                res = (float)bytesToInt<int8_t>(value);
                break;
            }
        case S16:
            {
                res = (float)bytesToInt<int16_t>(value);
                break;
            }
        case S32:
            {
                res = (float)bytesToInt<int32_t>(value);
                break;
            }
        case S64:
            {
                res = (float)bytesToInt<int64_t>(value);
                break;
            }
            
            
    }
    return res;
}

std::vector<uint8_t> TopTronicSensor::request_data() {
    return {
        0x01,   // message length
        0x40,   // operation
        function_group_,
        function_number_,
        (uint8_t)(datapoint_ >> 8),
        (uint8_t)(datapoint_),
    };
}

// uint32_t TopTronic::int_id_(std::string id) {
//     //split id HV_{function_group}_{function_number}_{datapoint}
//     std::vector<std::string> strings;
    
//     std::stringstream ss(id); 
//     std::string s;
//     while(getline(ss, s, '_')) {
//         strings.push_back(s);
//     }

//     return std::stoi(strings[1])            // function_group
//         + std::stoi(strings[2]) << 8        // function_number
//         + std::stoi(strings[2]) << 16;      // datapoint
// }

TopTronicDevice* TopTronic::get_or_create_device(uint32_t device_id) {
    if (devices_.count(device_id) <= 0) {
        devices_[device_id] = new TopTronicDevice();
    }
    return devices_[device_id];
}

void TopTronic::add_sensor(TopTronicSensor *sensor) {
    TopTronicDevice *device = get_or_create_device(sensor->get_device_id());
    device->sensors[sensor->get_id()] = sensor;
}

void TopTronic::send_requests() {
    for (const auto &d : devices_) {
        auto device = d.second;
        uint8_t message_id = 30;
        for (const auto &s : device->sensors) {
            auto sensor = s.second;
            uint32_t can_id = build_can_id(message_id, 200, 50, 50);
            canbus_->send_data(can_id, true, sensor->request_data());
            message_id += 1;
        }
    }
}

void TopTronic::setup() {
    send_requests();
}

void TopTronic::loop() {

}

void TopTronic::dump_config() {

}

void TopTronic::parse_frame(std::vector<uint8_t> data, uint32_t can_id, bool remote_transmission_request) {
    // check if operation is of type RESPONSE
    ESP_LOGD(TAG, "FRAME_START");
    ESP_LOGD(TAG, "can_id: %x", can_id);
    
    if (data[1] != 0x42) {
        ESP_LOGD(TAG, "ignoring: no response frame");
        return;
    }

    uint32_t device_id = can_id & 0xFFFF;

    if (devices_.count(device_id) <= 0) {
        ESP_LOGD(TAG, "ignoring: unknown device %x", device_id);
        return;
    }
    TopTronicDevice *device = devices_[device_id];   

    // check if sensor exists for the received value
    uint32_t datapoint = data[5] + (data[4] << 8);
    uint32_t id = data[2]
        + (data[3] << 8)
        + (datapoint << 16);

    if (device->sensors.count(id) <= 0) {
        ESP_LOGD(TAG, "ignoring: unknown sensor %x", device_id);
        return;
    }
    TopTronicSensor *sensor = device->sensors[id];

    float value = sensor->parse_value(std::vector<uint8_t>(data.begin() + 6, data.end()));
    ESP_LOGD(TAG, "publish %f", value);
    sensor->publish_state(value);
}

}  // namespace toptronic
}  // namespace esphome