#include "toptronic.h"
#include "esphome/core/log.h"

#include <sstream>
#include <string>
namespace esphome {
namespace toptronic {

static const char *const TAG = "tt";

uint32_t TopTronicBase::get_device_id() {
    return (device_type_ << 8) | device_addr_;
}

uint32_t build_can_id(uint8_t message_id, uint8_t priority, uint8_t device_type, uint8_t device_id) {
    return (message_id << 24) | (priority << 16) | (device_type << 8) | device_id;
}

std::vector<uint8_t> build_get_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint) {
    return {
        0x01,   // message length
        0x40,   // GET_REQUEST = 0x40
        function_group,
        function_number,
        (uint8_t)(datapoint >> 8),
        (uint8_t)(datapoint),
    };
}

std::vector<uint8_t> build_set_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint, std::vector<uint8_t> value) {
    std::vector<uint8_t> data = {
        0x01,   // message length
        0x46,   // SET_REQUEST = 0x46
        function_group,
        function_number,
        (uint8_t)(datapoint >> 8),
        (uint8_t)(datapoint),
    };

    for (int i = 0; i < value.size(); i++) {
        data.push_back(value[i]);
    }
    
    return data;
}

uint32_t TopTronicBase::get_id() {
    return function_group_
        + (function_number_ << 8)
        + (datapoint_ << 16);
}

std::vector<uint8_t> TopTronicBase::get_request_data() {
    return build_get_request(function_group_, function_number_, datapoint_);
}

template <typename T> 
T bytesToNumber(std::vector<uint8_t> value) {
    T a = 0;
    for(int i = 0; i < value.size(); i++) {
        a += value[i] << 8*i;
    }
    return a;
}

float bytesToFloat(std::vector<uint8_t> value, TypeName type) {
    switch(type) {
        case U8:
            {
                return (float)bytesToNumber<uint8_t>(value);
            }
        case U16:
            {
                return (float)bytesToNumber<uint16_t>(value);
            }
        case U32:
            {
                return (float)bytesToNumber<uint32_t>(value);
            }
        case S8:
            {
                return (float)bytesToNumber<int8_t>(value);
            }
        case S16:
            {
                return (float)bytesToNumber<int16_t>(value);
            }
        case S32:
            {
                return (float)bytesToNumber<int32_t>(value);
            }
        case S64:
            {
                return (float)bytesToNumber<int64_t>(value);
            }            
    }
    return 0.0f;
}

template <typename T> 
std::vector<uint8_t> numberToBytes(T value) {
    std::vector<uint8_t> a;
    for(int i = 0; i < sizeof(value); i++) {
        a.push_back((uint8_t)(value >> 8*i));
    }
    return a;
}

std::vector<uint8_t> floatToBytes(float value, TypeName type) {
    switch(type) {
        case U8:
            {
                return numberToBytes((uint8_t)value);
            }
        case U16:
            {
                return numberToBytes((uint16_t)value);
            }
        case U32:
            {
                return numberToBytes((uint32_t)value);
            }
        case S8:
            {
                return numberToBytes((int8_t)value);
            }
        case S16:
            {
                return numberToBytes((int16_t)value);
            }
        case S32:
            {
                return numberToBytes((int32_t)value);
            }
        case S64:
            {
                return numberToBytes((int64_t)value);
            }            
    }
    return {};
}

float TopTronicSensor::parse_value(std::vector<uint8_t> value) {
    return bytesToFloat(value, type_);
}

void TopTronicNumber::control(float value) {
    std::vector<uint8_t> bytes = floatToBytes(value, type_);

    uint32_t can_id = build_can_id(30, 200, 50, 50);
    std::vector<uint8_t> data = build_set_request(function_group_, function_number_, datapoint_, bytes);
    canbus_->send_data(can_id, true, data);

    ESP_LOGD(TAG, "%s: %f", get_name().c_str(), value);
}

std::string TopTronicTextSensor::parse_value(std::vector<uint8_t> value) {
    uint8_t intValue = bytesToNumber<uint8_t>(value);
    return toText_[intValue];
}

void TopTronicSelect::control(const std::string &text) {
    uint8_t value = toValue_[text];
    
    uint32_t can_id = build_can_id(30, 200, 50, 50);
    std::vector<uint8_t> data = build_set_request(function_group_, function_number_, datapoint_, {value});
    canbus_->send_data(can_id, true, data);

    ESP_LOGD(TAG, "%s: %s selected", get_name().c_str(), text.c_str());
}

TopTronicDevice* TopTronic::get_or_create_device(uint32_t device_id) {
    if (devices_.count(device_id) <= 0) {
        devices_[device_id] = new TopTronicDevice();
    }
    return devices_[device_id];
}

void TopTronic::add_sensor(TopTronicBase *sensor) {
    TopTronicDevice *device = get_or_create_device(sensor->get_device_id());
    device->sensors[sensor->get_id()] = sensor;
}

void TopTronic::add_input(TopTronicBase *input) {
    TopTronicDevice *device = get_or_create_device(input->get_device_id());
    device->inputs[input->get_id()] = input;
}

void TopTronic::get_sensors() {
    for (const auto &d : devices_) {
        auto device = d.second;
        uint8_t message_id = 30;
        for (const auto &s : device->sensors) {
            auto sensor = s.second;
            uint32_t can_id = build_can_id(message_id, 200, 50, 50);
            canbus_->send_data(can_id, true, sensor->get_request_data());
            message_id += 1;
        }
    }
}

TopTronicBase* TopTronic::get_sensor(uint32_t device_id, uint32_t sensor_id) {
    if (devices_.count(device_id) == 0) {
        return NULL;
    }
    TopTronicDevice* device = devices_[device_id];

    if (device->sensors.count(sensor_id) == 0) {
        return NULL;
    }
    return device->sensors[sensor_id];
}

void TopTronic::link_inputs() {
    ESP_LOGD(TAG, "Linking inputs ...");

    for (const auto &d : devices_) {
        auto device = d.second;
        for (const auto &i : device->inputs) {
            auto inputBase = i.second;
            auto sensorBase = get_sensor(inputBase->get_device_id(), inputBase->get_id());
            if (sensorBase == NULL) {
                continue;
            }
            if (sensorBase->type() == SENSOR) {
                auto sensor = (TopTronicSensor*) sensorBase;
            } else if (sensorBase->type() == TEXTSENSOR) {
                auto sensor = (TopTronicTextSensor*) sensorBase;
                auto input = (TopTronicSelect*) inputBase;
                sensor->add_on_state_callback([input](std::string state) -> void {
                    ESP_LOGD(TAG, "Updating %s", input->get_name().c_str());
                    input->publish_state(state);
                });
                ESP_LOGD(TAG, "Linked %s with %s", sensor->get_name().c_str(), input->get_name().c_str());
            }
        }
    }
}

void TopTronic::setup() {
    get_sensors();
    link_inputs();
}

void TopTronic::loop() {

}

void TopTronic::dump_config() {

}

void TopTronic::parse_frame(std::vector<uint8_t> data, uint32_t can_id, bool remote_transmission_request) {
    // check if operation is of type RESPONSE
    ESP_LOGD(TAG, "FRAME_START");
    ESP_LOGD(TAG, "can_id: 0x%X", can_id);
    
    if (data[1] != 0x42) {
        ESP_LOGD(TAG, "ignoring: no response frame");
        return;
    }

    uint32_t device_id = can_id & 0xFFFF;

    if (devices_.count(device_id) <= 0) {
        ESP_LOGD(TAG, "ignoring: unknown device 0x%X", device_id);
        return;
    }
    TopTronicDevice *device = devices_[device_id];   

    // check if sensor exists for the received value
    uint32_t datapoint = data[5] + (data[4] << 8);
    uint32_t id = data[2]
        + (data[3] << 8)
        + (datapoint << 16);

    if (device->sensors.count(id) <= 0) {
        ESP_LOGD(TAG, "ignoring: unknown sensor 0x%X", id);
        return;
    }
    TopTronicBase *sensorBase = device->sensors[id];

    if (sensorBase->type() == SENSOR) {
        TopTronicSensor *sensor = (TopTronicSensor*)sensorBase;
        float value = sensor->parse_value(std::vector<uint8_t>(data.begin() + 6, data.end()));
        ESP_LOGD(TAG, "publish %f", value);
        sensor->publish_state(value);
    } else if (sensorBase->type() == TEXTSENSOR) {
        TopTronicTextSensor *sensor = (TopTronicTextSensor*)sensorBase;
        std::string value = sensor->parse_value(std::vector<uint8_t>(data.begin() + 6, data.end()));
        sensor->publish_state(value);
    }
}

}  // namespace toptronic
}  // namespace esphome