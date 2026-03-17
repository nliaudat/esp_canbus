#include "toptronic.h"
#include "esphome/core/log.h"

#include <sstream>
#include <string>
#include <iomanip>

namespace esphome {
namespace toptronic {

static const char *const TAG = "tt";

static const uint8_t RESPONSE = 0x42;
static const uint8_t GET_REQ = 0x40;
static const uint8_t SET_REQ = 0x46;

// https://stackoverflow.com/a/14051107/3140799
std::string hex_str(const uint8_t *data, int len) {
  std::stringstream ss;
  ss << std::hex;
  for (int i = 0; i < len; ++i)
    ss << std::setw(2) << std::setfill('0') << (int) data[i];
  return ss.str();
}

uint32_t TopTronicBase::get_device_id() {
  return this->device_type_ | this->device_addr_;
}

uint32_t build_can_id(uint16_t sender_id, uint16_t receiver_mask) {
  return (0x7F << 22) | (sender_id << 11) | receiver_mask;
}

std::vector<uint8_t> build_get_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint) {
  return {
    0x01,            // message length
    GET_REQ,         // GET_REQUEST = 0x40
    function_group,
    function_number,
    (uint8_t)(datapoint >> 8),
    (uint8_t)(datapoint),
  };
}

std::vector<uint8_t> build_set_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint,
                                       const std::vector<uint8_t> &value) {
  std::vector<uint8_t> data = {
    0x01,            // message length
    SET_REQ,         // SET_REQUEST = 0x46
    function_group,
    function_number,
    (uint8_t)(datapoint >> 8),
    (uint8_t)(datapoint),
  };
  for (uint8_t byte : value) {
    data.push_back(byte);
  }
  return data;
}

uint32_t TopTronicBase::get_id() {
  return this->function_group_
      + (this->function_number_ << 8)
      + (this->datapoint_ << 16);
}

std::vector<uint8_t> TopTronicBase::get_request_data() {
  return build_get_request(this->function_group_, this->function_number_, this->datapoint_);
}

void TopTronicBase::add_on_set_callback(std::function<void(std::vector<uint8_t>)> &&callback) {
  this->set_callback_.add(std::move(callback));
}

void TopTronicBase::add_on_update_callback(std::function<void()> &&callback) {
  this->update_callback_.add(std::move(callback));
}

void TopTronicBase::update() {
  this->update_callback_.call();
}

template<typename T>
T bytes_to_number(const std::vector<uint8_t> &value) {
  T a = 0;
  for (size_t i = 0; i < value.size(); i++) {
    a = (a << 8) + value[i];
  }
  return a;
}

float bytes_to_float(const std::vector<uint8_t> &value, TypeName type) {
  switch (type) {
    case U8:  return (float) bytes_to_number<uint8_t>(value);
    case U16: return (float) bytes_to_number<uint16_t>(value);
    case U32: return (float) bytes_to_number<uint32_t>(value);
    case S8:  return (float) bytes_to_number<int8_t>(value);
    case S16: return (float) bytes_to_number<int16_t>(value);
    case S32: return (float) bytes_to_number<int32_t>(value);
    case S64: return (float) bytes_to_number<int64_t>(value);
  }
  return 0.0f;
}

template<typename T>
std::vector<uint8_t> number_to_bytes(T value) {
  std::vector<uint8_t> a;
  constexpr size_t size = sizeof(T);
  for (size_t i = 0; i < size; i++) {
    a.push_back((uint8_t)(value >> (8 * (size - i - 1))));
  }
  return a;
}

std::vector<uint8_t> float_to_bytes(float value, TypeName type) {
  switch (type) {
    case U8:  return number_to_bytes((uint8_t) value);
    case U16: return number_to_bytes((uint16_t) value);
    case U32: return number_to_bytes((uint32_t) value);
    case S8:  return number_to_bytes((int8_t) value);
    case S16: return number_to_bytes((int16_t) value);
    case S32: return number_to_bytes((int32_t) value);
    case S64: return number_to_bytes((int64_t) value);
  }
  return {};
}

float TopTronicSensor::parse_value(const std::vector<uint8_t> &value) {
  return bytes_to_float(value, this->type_);
}

void TopTronicNumber::control(float value) {
  float v = this->multiplier_ * value;
  std::vector<uint8_t> bytes = float_to_bytes(v, this->type_);

  std::vector<uint8_t> data =
      build_set_request(this->function_group_, this->function_number_, this->datapoint_, bytes);
  this->set_callback_.call(data);

  ESP_LOGI(TAG, "[SET] %s: %f, Data: 0x%s", this->get_name().c_str(), v, hex_str(&data[0], data.size()).c_str());
}

std::string TopTronicTextSensor::parse_value(const std::vector<uint8_t> &value) {
  uint8_t int_value = bytes_to_number<uint8_t>(value);
  return this->to_text_[int_value];
}

void TopTronicSelect::control(const std::string &text) {
  uint8_t value = this->to_value_[text];

  std::vector<uint8_t> data =
      build_set_request(this->function_group_, this->function_number_, this->datapoint_, {value});
  this->set_callback_.call(data);

  ESP_LOGI(TAG, "[SET] %s: %s, Data: 0x%s", this->get_name().c_str(), text.c_str(),
           hex_str(&data[0], data.size()).c_str());
}

TopTronicDevice *TopTronic::get_or_create_device(uint32_t device_id) {
  if (this->devices_.count(device_id) == 0) {
    this->devices_[device_id] = std::make_unique<TopTronicDevice>();
  }
  return this->devices_[device_id].get();
}

void TopTronic::add_sensor(TopTronicBase *sensor) {
  TopTronicDevice *device = this->get_or_create_device(sensor->get_device_id());
  device->sensors[sensor->get_id()] = sensor;
}

void TopTronic::add_input(TopTronicBase *input) {
  TopTronicDevice *device = this->get_or_create_device(input->get_device_id());
  device->inputs[input->get_id()] = input;
}

void TopTronic::register_sensor_callbacks() {
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &s : device->sensors) {
      auto *sensor = s.second;
      auto *canbus = this->canbus_;
      uint32_t can_id = build_can_id(this->device_type_ | this->device_addr_, sensor->get_device_id());

      sensor->add_on_update_callback([canbus, sensor, can_id]() -> void {
        auto data = sensor->get_request_data();
        canbus->send_data(can_id, true, data);
        ESP_LOGD(TAG, "[GET] Data: 0x%s", hex_str(&data[0], data.size()).c_str());
      });
    }
  }
}

void TopTronic::register_input_callbacks() {
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &i : device->inputs) {
      auto *input = i.second;
      auto *canbus = this->canbus_;
      uint32_t can_id = build_can_id(this->device_type_ | this->device_addr_, input->get_device_id());

      input->add_on_set_callback([canbus, input, can_id](std::vector<uint8_t> data) -> void {
        canbus->send_data(can_id, true, data);
      });
    }
  }
}

TopTronicBase *TopTronic::get_sensor(uint32_t device_id, uint32_t sensor_id) {
  if (this->devices_.count(device_id) == 0) {
    return nullptr;
  }
  TopTronicDevice *device = this->devices_[device_id].get();

  if (device->sensors.count(sensor_id) == 0) {
    return nullptr;
  }
  return device->sensors[sensor_id];
}

void TopTronic::link_inputs() {
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &i : device->inputs) {
      auto *input_base = i.second;
      auto *sensor_base = this->get_sensor(input_base->get_device_id(), input_base->get_id());
      if (sensor_base == nullptr) {
        continue;
      }
      if (sensor_base->type() == SENSOR) {
        auto *sensor = (TopTronicSensor *) sensor_base;
        auto *input = (TopTronicNumber *) input_base;
        sensor->add_on_raw_state_callback([input](float state) -> void {
          float divider = input->get_multiplier();
          input->publish_state(state / divider);
        });
      } else if (sensor_base->type() == TEXTSENSOR) {
        auto *sensor = (TopTronicTextSensor *) sensor_base;
        auto *input = (TopTronicSelect *) input_base;
        sensor->add_on_raw_state_callback([input](std::string state) -> void {
          input->publish_state(state);
        });
      }
    }
  }
}

void TopTronic::setup() {
  this->link_inputs();
  this->register_sensor_callbacks();
  this->register_input_callbacks();
}

void TopTronic::loop() {}

void TopTronic::dump_config() {}

void log_response_frame(const std::vector<uint8_t> &data, uint32_t can_id, const std::string &sensor_name) {
  ESP_LOGI(TAG, "[RES] Can-ID: 0x%08X, Sensor: %s, Data: 0x%s", can_id, sensor_name.c_str(),
           hex_str(&data[0], data.size()).c_str());
}

void TopTronic::parse_frame(const std::vector<uint8_t> &data, uint32_t can_id, bool remote_transmission_request) {
  uint8_t msg_id = can_id >> 24;

  if (msg_id == 0x1f) {
    // Start of a message
    uint8_t msg_len = data[0] >> 3;
    if (msg_len == 0) {
      // Full message — strip size byte and dispatch
      this->interpret_message(std::vector<uint8_t>(data.begin() + 1, data.end()), can_id,
                              remote_transmission_request);
    } else {
      // Multi-frame message: store first fragment
      uint8_t msg_header = data[1];
      ESP_LOGD(TAG, "     - Start of message with id: %d with length %d", msg_header, msg_len);
      if (this->pending_messages_.size() >= 16) {
        ESP_LOGW(TAG, "Pending message buffer full (%zu entries), stale fragments may exist",
                 this->pending_messages_.size());
      }
      this->pending_messages_[msg_header] =
          std::make_pair(std::vector<uint8_t>(data.begin() + 2, data.end()), msg_len - 1);
    }
  } else {
    uint8_t msg_header = data[0];
    auto it = this->pending_messages_.find(msg_header);
    if (it != this->pending_messages_.end()) {
      auto &pending_msg = it->second;
      auto msg_len = pending_msg.second - 1;
      ESP_LOGD(TAG, "     - Part of message with id: %d with remaining length %d", msg_header, msg_len);
      pending_msg.first.insert(pending_msg.first.end(), data.begin() + 1, data.end());
      if (msg_len == 0) {
        // Strip trailing CRC bytes and dispatch
        auto real_msg = std::vector<uint8_t>(pending_msg.first.begin(), pending_msg.first.end() - 2);
        this->pending_messages_.erase(msg_header);
        this->interpret_message(real_msg, can_id, remote_transmission_request);
      } else {
        pending_msg.second = msg_len;
      }
    }
  }
}

void TopTronic::interpret_message(const std::vector<uint8_t> &data, uint32_t can_id,
                                  bool remote_transmission_request) {
  if (data[0] == GET_REQ) {
    ESP_LOGD(TAG, "[GET] Can-ID: 0x%08X, Data: 0x%s", can_id, hex_str(&data[0], data.size()).c_str());
    return;
  }

  if (data[0] == SET_REQ) {
    ESP_LOGI(TAG, "[SET] Can-ID: 0x%08X, Data: 0x%s", can_id, hex_str(&data[0], data.size()).c_str());
    return;
  }

  if (data[0] != RESPONSE) {
    ESP_LOGD(TAG, "[UNK] Can-ID: 0x%08X, Data: 0x%s", can_id, hex_str(&data[0], data.size()).c_str());
    return;
  }

  uint32_t device_id = (can_id >> 11) & 0x7FF;

  if (this->devices_.count(device_id) == 0) {
    return;
  }
  TopTronicDevice *device = this->devices_[device_id].get();

  // Check if a sensor exists for the received value
  uint32_t datapoint = data[4] + (data[3] << 8);
  uint32_t id = data[1]        // function_group
      + (data[2] << 8)         // function_number
      + (datapoint << 16);

  if (device->sensors.count(id) == 0) {
    return;
  }
  TopTronicBase *sensor_base = device->sensors[id];

  if (sensor_base->type() == SENSOR) {
    auto *sensor = (TopTronicSensor *) sensor_base;
    float value = sensor->parse_value(std::vector<uint8_t>(data.begin() + 5, data.end()));
    sensor->publish_state(value);
    log_response_frame(data, can_id, sensor->get_name());
  } else if (sensor_base->type() == TEXTSENSOR) {
    auto *sensor = (TopTronicTextSensor *) sensor_base;
    std::string value = sensor->parse_value(std::vector<uint8_t>(data.begin() + 5, data.end()));
    sensor->publish_state(value);
    log_response_frame(data, can_id, sensor->get_name());
  }
}

}  // namespace toptronic
}  // namespace esphome