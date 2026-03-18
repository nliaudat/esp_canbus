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

// Format a byte buffer as a zero-padded hex string for log output (e.g. "0x4001001A").
// Reference: https://stackoverflow.com/a/14051107/3140799
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

// Build a 29-bit extended CAN ID using the TopTronic addressing scheme:
//   bits 28-22 : fixed 0x7F priority/type marker
//   bits 21-11 : sender node ID
//   bits 10-0  : receiver node ID (or broadcast mask)
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

// Build a SET request payload. The result may exceed 8 bytes for large value types
// (U32/S32 = 10 bytes, S64 = 14 bytes). The caller is responsible for splitting
// the payload into multiple CAN frames via send_can_frames() if needed.
std::vector<uint8_t> build_set_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint,
                                       const std::vector<uint8_t> &value) {
  std::vector<uint8_t> data = {
    0x01,            // message length / frame flags (upper 5 bits = 0 → single frame signal)
    SET_REQ,         // SET_REQUEST = 0x46
    function_group,
    function_number,
    (uint8_t)(datapoint >> 8),
    (uint8_t)(datapoint),
  };
  data.insert(data.end(), value.begin(), value.end());
  return data;
}

// Pack the three protocol fields into a single uint32 used as a lookup key.
// Layout: [datapoint(16) | function_number(8) | function_group(8)]
uint32_t TopTronicBase::get_id() {
  return this->function_group_
      + (this->function_number_ << 8)
      + (this->datapoint_ << 16);
}

// Returns a const reference to avoid copying the vector on every polling cycle.
const std::vector<uint8_t> &TopTronicBase::get_request_data() {
  return this->request_data_;
}

// Called once at setup time so subsequent poll callbacks read from a cached buffer.
void TopTronicBase::cache_request_data() {
  this->request_data_ = build_get_request(this->function_group_, this->function_number_, this->datapoint_);
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

// Decode a big-endian byte sequence into an integer of type T.
// Accumulates into uint64_t to avoid signed-shift UB when T is int64_t
// (left-shifting into the sign bit is undefined for signed types in C++).
// static_cast<T> of an out-of-range uint64_t is implementation-defined but
// produces the expected two's-complement result on all ESPHome targets.
template<typename T>
T bytes_to_number(const std::vector<uint8_t> &value) {
  uint64_t u = 0;
  for (size_t i = 0; i < value.size(); i++) {
    u = (u << 8) | value[i];
  }
  return static_cast<T>(u);
}

// Convert raw CAN bytes to a float, interpreting them as the configured integer type.
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

// Encode a numeric value as a big-endian byte sequence for a SET request payload.
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
  auto it = this->to_text_.find(int_value);
  if (it == this->to_text_.end()) {
    ESP_LOGW(TAG, "Unknown text sensor value: %u", int_value);
    return "";
  }
  return it->second;
}

void TopTronicSelect::control(const std::string &text) {
  auto it = this->to_value_.find(text);
  if (it == this->to_value_.end()) {
    ESP_LOGW(TAG, "[SET] Unknown option '%s' — ignoring", text.c_str());
    return;
  }
  uint8_t value = it->second;

  std::vector<uint8_t> data =
      build_set_request(this->function_group_, this->function_number_, this->datapoint_, {value});
  this->set_callback_.call(data);

  ESP_LOGI(TAG, "[SET] %s: %s, Data: 0x%s", this->get_name().c_str(), text.c_str(),
           hex_str(&data[0], data.size()).c_str());
}

// Return the TopTronicDevice for this ID, creating it on first access.
// operator[] performs a single map lookup rather than count() + operator[] (two lookups).
TopTronicDevice *TopTronic::get_or_create_device(uint32_t device_id) {
  auto &device_ptr = this->devices_[device_id];
  if (!device_ptr) {
    device_ptr = std::make_unique<TopTronicDevice>();
  }
  return device_ptr.get();
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
      sensor->cache_request_data();  // build once, avoid per-poll heap alloc
      auto *canbus = this->canbus_;
      uint32_t can_id = build_can_id(this->device_type_ | this->device_addr_, sensor->get_device_id());

      sensor->add_on_update_callback([canbus, sensor, can_id]() -> void {
        const auto &data = sensor->get_request_data();
        canbus->send_data(can_id, true, data);
        ESP_LOGD(TAG, "[GET] Data: 0x%s", hex_str(&data[0], data.size()).c_str());
      });
    }
  }
}

static uint32_t reflect(uint32_t val, uint8_t width) {
  uint32_t out = 0;
  for (uint8_t i = 0; i < width; ++i) {
    out = (out << 1) | (val & 1);
    val >>= 1;
  }
  return out;
}

// CRC-16 used by the TopTronic multi-frame protocol.
// Parameters identified by brute-force search against captured bus traffic:
//   poly=0x1021  init=0xB006  refin=true  refout=true  xorout=0x0000
// This matches the CRC-16/ARC family with a non-standard init value.
static uint16_t compute_crc16(const uint8_t *data, size_t len) {
  uint16_t crc = 0xB006;  // init
  for (size_t i = 0; i < len; ++i) {
    uint8_t byte = static_cast<uint8_t>(reflect(data[i], 8));
    for (int b = 7; b >= 0; --b) {
      uint8_t bit = (byte >> b) & 1;
      uint8_t top = (crc >> 15) & 1;
      crc = static_cast<uint16_t>((crc << 1) ^ (top ^ bit ? 0x1021 : 0));
    }
  }
  return static_cast<uint16_t>(reflect(crc, 16));  // refout=true, xorout=0x0000
}

// Send a SET request over CAN, transparently splitting into multiple frames when needed.
//
// A standard CAN frame holds at most 8 bytes. The TopTronic multi-frame protocol works as:
//   First frame  (msg_id = 0x1F): [frame_count<<3|flags, msg_header, payload[0..5]]
//   Cont. frames (msg_id ≠ 0x1F): [msg_header, payload[6..12], ...]
//   Last 2 bytes of the reassembled payload are the CRC-16 checksum (poly=0x1021, init=0xB006).
//
// The continuation CAN ID clears bits 28-22 (sets the top-priority field to 0) so that
// parse_frame() on the receiver treats those frames as continuations, not new messages.
static void send_can_frames(canbus::Canbus *canbus, uint32_t can_id, const std::vector<uint8_t> &data) {
  if (data.size() <= 8) {
    // Single-frame: payload fits in one CAN frame — send as-is.
    canbus->send_data(can_id, true, data);
    return;
  }

  // Multi-frame: strip the first byte (0x01 single-frame flag) and reframe.
  // A static counter provides a unique msg_header key for each outgoing multi-frame message.
  static uint8_t msg_counter = 0;
  uint8_t msg_header = (++msg_counter == 0) ? ++msg_counter : msg_counter;  // skip 0

  // Build the full message payload, then append the 2-byte CRC (big-endian).
  std::vector<uint8_t> msg(data.begin() + 1, data.end());
  uint16_t crc = compute_crc16(msg.data(), msg.size());
  msg.push_back(static_cast<uint8_t>(crc >> 8));    // CRC high byte
  msg.push_back(static_cast<uint8_t>(crc & 0xFF));  // CRC low byte

  // First frame carries up to 6 message bytes (2 header bytes consume slots 0 and 1).
  size_t first_chunk = std::min<size_t>(6, msg.size());
  size_t after_first = msg.size() - first_chunk;
  auto num_cont = static_cast<uint8_t>((after_first + 6) / 7);  // ceil(remaining / 7)

  std::vector<uint8_t> first_frame;
  first_frame.push_back(static_cast<uint8_t>((num_cont << 3) | 0x01));  // frame count in upper 5 bits
  first_frame.push_back(msg_header);                                      // reassembly key
  first_frame.insert(first_frame.end(), msg.begin(), msg.begin() + first_chunk);
  canbus->send_data(can_id, true, first_frame);

  // Continuation frames use a lower-priority CAN ID (bits 28-22 cleared → msg_id ≠ 0x1F).
  uint32_t cont_id = can_id & 0x003FFFFF;
  std::vector<uint8_t> cont_frame;
  cont_frame.reserve(8);
  for (size_t offset = first_chunk; offset < msg.size();) {
    size_t chunk = std::min<size_t>(7, msg.size() - offset);
    cont_frame.clear();
    cont_frame.push_back(msg_header);
    cont_frame.insert(cont_frame.end(), msg.begin() + offset, msg.begin() + offset + chunk);
    offset += chunk;
    canbus->send_data(cont_id, true, cont_frame);
  }

  ESP_LOGD(TAG, "[SET] Sent %u CAN frames (msg_header=0x%02X, payload=%zu bytes)",
           1 + num_cont, msg_header, data.size());
}

void TopTronic::register_input_callbacks() {
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &i : device->inputs) {
      auto *input = i.second;
      auto *canbus = this->canbus_;
      uint32_t can_id = build_can_id(this->device_type_ | this->device_addr_, input->get_device_id());

      input->add_on_set_callback([canbus, input, can_id](std::vector<uint8_t> data) -> void {
        // send_can_frames handles single-frame (≤8 bytes) and multi-frame (>8 bytes) automatically.
        send_can_frames(canbus, can_id, data);
      });
    }
  }
}

// Look up a sensor by its (device_id, sensor_id) pair.
// Uses find() on both maps so each is traversed at most once (no double-lookup).
TopTronicBase *TopTronic::get_sensor(uint32_t device_id, uint32_t sensor_id) {
  auto device_it = this->devices_.find(device_id);
  if (device_it == this->devices_.end()) {
    return nullptr;  // device not registered — ignore
  }
  TopTronicDevice *device = device_it->second.get();

  auto sensor_it = device->sensors.find(sensor_id);
  if (sensor_it == device->sensors.end()) {
    return nullptr;  // sensor not registered for this device — ignore
  }
  return sensor_it->second;
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

// Handle a raw CAN frame from the bus.
//
// The TopTronic protocol uses two CAN ID ranges:
//   msg_id == 0x1F  →  start-of-message frame
//   other           →  continuation frame for a multi-frame message
//
// Short messages (msg_len == 0) fit in one frame and are dispatched immediately.
// Longer messages are split into multiple CAN frames and reassembled in pending_messages_
// using msg_header as the reassembly key. Once all fragments arrive the message is dispatched.
void TopTronic::parse_frame(const std::vector<uint8_t> &data, uint32_t can_id, bool remote_transmission_request) {
  uint8_t msg_id = can_id >> 24;

  if (msg_id == 0x1f) {
    // First frame of a message. data[0] upper 5 bits = number of remaining frames.
    uint8_t msg_len = data[0] >> 3;
    if (msg_len == 0) {
      // Single-frame message: strip the length byte and dispatch directly.
      this->interpret_message(std::vector<uint8_t>(data.begin() + 1, data.end()), can_id,
                              remote_transmission_request);
    } else {
      // Multi-frame message: save the first fragment and wait for the rest.
      uint8_t msg_header = data[1];  // reassembly key shared across all frames of this message
      ESP_LOGD(TAG, "     - Start of message with id: %d with length %d", msg_header, msg_len);
      if (this->pending_messages_.size() >= 16) {
        // A large backlog means start frames from other devices (or lost fragments) accumulated.
        ESP_LOGW(TAG, "Pending message buffer full (%zu entries), clearing stale fragments",
                 this->pending_messages_.size());
        this->pending_messages_.clear();
      }
      auto initial_data = std::vector<uint8_t>(data.begin() + 2, data.end());
      // Pre-allocate: each continuation frame carries at most 7 payload bytes (8 - header byte).
      initial_data.reserve(static_cast<size_t>(msg_len) * 7);
      this->pending_messages_[msg_header] = std::make_pair(std::move(initial_data), msg_len - 1);
    }
  } else {
    // Continuation frame: append payload to the in-progress message.
    uint8_t msg_header = data[0];
    auto it = this->pending_messages_.find(msg_header);
    if (it != this->pending_messages_.end()) {
      auto &pending_msg = it->second;
      auto msg_len = pending_msg.second - 1;  // decrement remaining frame count
      ESP_LOGD(TAG, "     - Part of message with id: %d with remaining length %d", msg_header, msg_len);
      pending_msg.first.insert(pending_msg.first.end(), data.begin() + 1, data.end());
      if (msg_len == 0) {
        if (pending_msg.first.size() < 2) {
          ESP_LOGW(TAG, "Reassembled message too short for CRC (%zu bytes)", pending_msg.first.size());
          this->pending_messages_.erase(msg_header);
          return;
        }

        uint16_t received_crc = (pending_msg.first[pending_msg.first.size() - 2] << 8) | pending_msg.first[pending_msg.first.size() - 1];
        uint16_t computed_crc = compute_crc16(pending_msg.first.data(), pending_msg.first.size() - 2);

        if (received_crc != computed_crc) {
          ESP_LOGW(TAG, "CRC check failed! Recv: 0x%04X, Comp: 0x%04X", received_crc, computed_crc);
          this->pending_messages_.erase(msg_header);
          return;
        }

        auto real_msg = std::vector<uint8_t>(pending_msg.first.begin(), pending_msg.first.end() - 2);
        this->pending_messages_.erase(msg_header);  // free reassembly buffer
        this->interpret_message(real_msg, can_id, remote_transmission_request);
      } else {
        pending_msg.second = msg_len;  // store updated remaining count
      }
    }
  }
}

// Dispatch a fully reassembled TopTronic message.
//
// Message byte layout (after the CAN framing bytes are stripped):
//   [0]   command byte  (0x40 GET, 0x46 SET, 0x42 RESPONSE)
//   [1]   function_group
//   [2]   function_number
//   [3]   datapoint high byte
//   [4]   datapoint low byte
//   [5..] value payload
void TopTronic::interpret_message(const std::vector<uint8_t> &data, uint32_t can_id,
                                  bool remote_transmission_request) {
  // Ignore outgoing GET/SET requests that we echoed ourselves — nothing to update.
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

  // The sender node ID sits in bits 21-11 of the CAN ID.
  uint32_t device_id = (can_id >> 11) & 0x7FF;

  auto device_it = this->devices_.find(device_id);
  if (device_it == this->devices_.end()) {
    return;  // message from a device we have no entities registered for — ignore
  }
  TopTronicDevice *device = device_it->second.get();

  // Reconstruct the sensor lookup key from the protocol fields in the response.
  uint32_t datapoint = data[4] + (data[3] << 8);
  uint32_t id = data[1]        // function_group
      + (data[2] << 8)         // function_number
      + (datapoint << 16);

  auto sensor_it = device->sensors.find(id);
  if (sensor_it == device->sensors.end()) {
    return;  // no sensor registered for this datapoint — ignore
  }
  TopTronicBase *sensor_base = sensor_it->second;

  // Downcast to the concrete type and publish the decoded value.
  // data[5..] contains the raw value bytes.
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