#include "toptronic.h"

#include <sstream>
#include <string>

namespace esphome {
namespace toptronic {

uint32_t TopTronicSensor::get_can_id() {
    return 0; //TODO
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
        case U16:
        case U32:
            {
                uint32_t u = bytesToInt<uint32_t>(value);
                res = (float)u;
                break;
            }
        case S8:
        case S16:
        case S32:
        case S64:
            {
                int32_t s = bytesToInt<int32_t>(value);
                res = (float)s;
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

TopTronicDevice* TopTronic::get_or_create_device(uint32_t can_id) {
    if (devices_.count(can_id) <= 0) {
        devices_[can_id] = new TopTronicDevice();
    }
    return devices_[can_id];
}

void TopTronic::add_sensor(TopTronicSensor *sensor) {
    TopTronicDevice *device = get_or_create_device(sensor->get_can_id());
    device->sensors[sensor->get_id()] = sensor;
}

void TopTronic::setup() {
    
    // send requests
    for (const auto &d : devices_) {
        auto device = d.second;
        for (const auto &s : device->sensors) {
            auto sensor = s.second;
            canbus_->send_data(sensor->get_can_id(), true, sensor->request_data());
        }
    }
}

void TopTronic::loop() {

}

void TopTronic::dump_config() {

}

void TopTronic::parse_frame(std::vector<uint8_t> data, uint32_t can_id, bool remote_transmission_request) {
    // check if operation is of type RESPONSE
    if (data[1] != 0x42) {
        return;
    }

    if (devices_.count(can_id) <= 0) {
        return;
    }
    TopTronicDevice *device = devices_[can_id];   

    // check if sensor exists for the received value
    uint32_t datapoint = data[5] + (data[4] << 8);
    uint32_t id = data[2]
        + (data[3] << 8)
        + (datapoint << 16);

    if (device->sensors.count(id) <= 0) {
        return;
    }
    TopTronicSensor *sensor = device->sensors[id];

    float value = sensor->parse_value(std::vector<uint8_t>(data.begin() + 6, data.end()));
    sensor->publish_state(value);
}

}  // namespace toptronic
}  // namespace esphome