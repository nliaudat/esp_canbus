#include "toptronic.h"
#include "esphome/core/log.h"

#include <string>

namespace esphome::toptronic {

static const char *const TAG = "toptronic";

static const uint8_t RESPONSE = 0x42;
// 0x56 = extended-format RESPONSE (larger value payload, e.g. cleaning /
// maint. counters). Same layout as 0x42 but 2 extra bytes (0x80 0x00) between
// the datapoint and the value.
static const uint8_t RESPONSE_EXT = 0x56;
static const uint8_t GET_REQ = 0x40;
static const uint8_t SET_REQ = 0x46;

// Minimum decodable TopTronic message: cmd | function_group | function_number | dp_hi | dp_lo.
static constexpr size_t MIN_MESSAGE_LEN = 5;

// Debug frame logging modes. The mode is build-wide shared state, NOT per-hub:
// with multiple toptronic hubs every hub receives every CAN frame, so logging
// must be deduplicated (see the single debug callback registered in setup()).
// The mode resets to OFF on every boot, so it can never become a permanent
// setting. 0 = off, 1 = candump (all frames), 2 = find can_id (data[1] == 0x42
// response or 0x40 request only).
enum DebugMode : uint8_t { DEBUG_MODE_OFF = 0, DEBUG_MODE_CANDUMP = 1, DEBUG_MODE_FIND_CAN_ID = 2 };
static DebugMode s_debug_mode = DEBUG_MODE_OFF;
static bool s_debug_callback_registered = false;

// Runtime-gated logging: when CANDUMP debug mode is active, silence ALL normal
// toptronic output so the candump lines (tag "candump") are the only thing on
// the bus/log path. The debug-mode transition messages in cycle_debug_mode()
// and dump_config() intentionally use raw ESP_LOG* so they always appear.
#define TT_LOGD(...) do { if (s_debug_mode != DEBUG_MODE_CANDUMP) { ESP_LOGD(TAG, __VA_ARGS__); } } while (0)
#define TT_LOGI(...) do { if (s_debug_mode != DEBUG_MODE_CANDUMP) { ESP_LOGI(TAG, __VA_ARGS__); } } while (0)
#define TT_LOGW(...) do { if (s_debug_mode != DEBUG_MODE_CANDUMP) { ESP_LOGW(TAG, __VA_ARGS__); } } while (0)

// Forward declaration: defined after TopTronic::setup() but referenced by the
// deduplicated debug callback registered there.
static void debug_log_frame(const std::vector<uint8_t> &data, uint32_t can_id);

// Format a byte buffer as a zero-padded hex string for log output (e.g. "4001001a").
// Uses a plain std::string (no std::stringstream) — common short messages fit in the
// small-string-optimization buffer, so the hot path (every received frame) performs
// no heap allocation.
std::string hex_str(const uint8_t *data, size_t len) {
  static const char *const HEX = "0123456789abcdef";
  std::string out;
  out.reserve(len * 2);
  for (size_t i = 0; i < len; ++i) {
    out.push_back(HEX[(data[i] >> 4) & 0x0F]);
    out.push_back(HEX[data[i] & 0x0F]);
  }
  return out;
}

// The ESP32 CAN gateway presents itself on the bus as a TopTronic gateway (GW)
// device. This constant is the device-type portion of the sender CAN ID for all
// outgoing requests.
static constexpr uint16_t GATEWAY_DEVICE_TYPE = 1153;  // GW

// Build a 29-bit extended CAN ID using the TopTronic addressing scheme:
//   bits 28-22 : fixed 0x7F priority/type marker
//   bits 21-11 : sender node ID
//   bits 10-0  : receiver node ID (or broadcast mask)
uint32_t build_can_id(uint16_t sender_id, uint16_t receiver_mask) {
  return (0x7F << 22) | (sender_id << 11) | receiver_mask;
}

std::vector<uint8_t> build_get_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint) {
  return {
      0x01,     // message length
      GET_REQ,  // GET_REQUEST = 0x40
      function_group, function_number, (uint8_t) (datapoint >> 8), (uint8_t) (datapoint),
  };
}

// Build a SET request payload. The result may exceed 8 bytes for large value types
// (U32/S32 = 10 bytes, S64 = 14 bytes). The caller is responsible for splitting
// the payload into multiple CAN frames via send_can_frames() if needed.
std::vector<uint8_t> build_set_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint,
                                       const std::vector<uint8_t> &value) {
  std::vector<uint8_t> data = {
      0x01,     // message length / frame flags (upper 5 bits = 0 → single frame signal)
      SET_REQ,  // SET_REQUEST = 0x46
      function_group, function_number, (uint8_t) (datapoint >> 8), (uint8_t) (datapoint),
  };
  data.insert(data.end(), value.begin(), value.end());
  return data;
}

// Pack the three protocol fields into a single uint32 used as a lookup key.
// Layout: [datapoint(16) | function_number(8) | function_group(8)]
uint32_t TopTronicBase::get_id() {
  return this->function_group_ + (this->function_number_ << 8) + (this->datapoint_ << 16);
}

// Returns a const reference to avoid copying the vector on every polling cycle.
const std::vector<uint8_t> &TopTronicBase::get_request_data() { return this->request_data_; }

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

void TopTronicBase::update() { this->update_callback_.call(); }

// Decode a big-endian byte sequence into an integer of type T.
// Accumulates into uint64_t to avoid signed-shift UB when T is int64_t
// (left-shifting into the sign bit is undefined for signed types in C++).
// static_cast<T> of an out-of-range uint64_t is implementation-defined but
// produces the expected two's-complement result on all ESPHome targets.
template<typename T> T bytes_to_number(const uint8_t *data, size_t len) {
  uint64_t u = 0;
  for (size_t i = 0; i < len; i++) {
    u = (u << 8) | data[i];
  }
  return static_cast<T>(u);
}

// Convert raw CAN bytes to a float, interpreting them as the configured integer type.
float bytes_to_float(const uint8_t *data, size_t len, TypeName type) {
  switch (type) {
    case U8:
      return (float) bytes_to_number<uint8_t>(data, len);
    case U16:
      return (float) bytes_to_number<uint16_t>(data, len);
    case U32:
      return (float) bytes_to_number<uint32_t>(data, len);
    case S8:
      return (float) bytes_to_number<int8_t>(data, len);
    case S16:
      return (float) bytes_to_number<int16_t>(data, len);
    case S32:
      return (float) bytes_to_number<int32_t>(data, len);
    case S64:
      return (float) bytes_to_number<int64_t>(data, len);
  }
  return 0.0f;
}

// Encode a numeric value as a big-endian byte sequence for a SET request payload.
template<typename T> std::vector<uint8_t> number_to_bytes(T value) {
  std::vector<uint8_t> a;
  constexpr size_t size = sizeof(T);
  for (size_t i = 0; i < size; i++) {
    a.push_back((uint8_t) (value >> (8 * (size - i - 1))));
  }
  return a;
}

std::vector<uint8_t> float_to_bytes(float value, TypeName type) {
  switch (type) {
    case U8:
      return number_to_bytes((uint8_t) value);
    case U16:
      return number_to_bytes((uint16_t) value);
    case U32:
      return number_to_bytes((uint32_t) value);
    case S8:
      return number_to_bytes((int8_t) value);
    case S16:
      return number_to_bytes((int16_t) value);
    case S32:
      return number_to_bytes((int32_t) value);
    case S64:
      return number_to_bytes((int64_t) value);
  }
  return {};
}

#ifdef USE_SENSOR
float TopTronicSensor::parse_value(const uint8_t *data, size_t len) { return bytes_to_float(data, len, this->type_); }
#endif

#ifdef USE_NUMBER
void TopTronicNumber::control(float value) {
  float v = this->multiplier_ * value;
  std::vector<uint8_t> bytes = float_to_bytes(v, this->type_);

  std::vector<uint8_t> data = build_set_request(this->function_group_, this->function_number_, this->datapoint_, bytes);
  this->set_callback_.call(data);

  TT_LOGD("[SET] %s: %f, Data: 0x%s", this->get_name().c_str(), v, hex_str(data.data(), data.size()).c_str());
}
#endif

#ifdef USE_TEXT_SENSOR
std::string TopTronicTextSensor::parse_value(const uint8_t *data, size_t len) {
  uint8_t int_value = bytes_to_number<uint8_t>(data, len);
  auto it = this->to_text_.find(int_value);
  if (it == this->to_text_.end()) {
    TT_LOGW("Unknown text sensor value: %u", int_value);
    return "";
  }
  return it->second;
}
#endif

#ifdef USE_SELECT
void TopTronicSelect::control(const std::string &text) {
  auto it = this->to_value_.find(text);
  if (it == this->to_value_.end()) {
    TT_LOGW("[SET] Unknown option '%s' — ignoring", text.c_str());
    return;
  }
  uint8_t value = it->second;

  std::vector<uint8_t> data = build_set_request(this->function_group_, this->function_number_, this->datapoint_,
                                                float_to_bytes(static_cast<float>(value), this->type_));
  this->set_callback_.call(data);

  TT_LOGD("[SET] %s: %s, Data: 0x%s", this->get_name().c_str(), text.c_str(),
          hex_str(data.data(), data.size()).c_str());
}
#endif

#ifdef USE_BUTTON
void TopTronicButton::press_action() {
  std::vector<uint8_t> bytes = float_to_bytes(this->value_, this->type_);
  std::vector<uint8_t> data = build_set_request(this->function_group_, this->function_number_, this->datapoint_, bytes);
  this->set_callback_.call(data);

  TT_LOGD("[SET] %s: %f, Data: 0x%s", this->get_name().c_str(), this->value_,
          hex_str(data.data(), data.size()).c_str());
}
#endif

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
  TopTronicDevice *device = this->get_or_create_device(this->get_device_id());
  device->sensors[sensor->get_id()] = sensor;
}

void TopTronic::add_input(TopTronicBase *input) {
  TopTronicDevice *device = this->get_or_create_device(this->get_device_id());
  device->inputs[input->get_id()] = input;
}

void TopTronic::register_sensor_callbacks() {
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &s : device->sensors) {
      auto *sensor = s.second;
      sensor->cache_request_data();  // build once, avoid per-poll heap alloc
      auto *canbus = this->canbus_;
      uint32_t can_id = build_can_id(GATEWAY_DEVICE_TYPE | this->device_addr_, this->get_device_id());

      sensor->add_on_update_callback([canbus, sensor, can_id]() -> void {
        const auto &data = sensor->get_request_data();
        canbus->send_data(can_id, true, data);
        TT_LOGD("[GET] Data: 0x%s", hex_str(data.data(), data.size()).c_str());
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
//
// Lookup-table form: the bit-wise algorithm reflects each input byte, runs an
// MSB-first (left-shifting) poly 0x1021 loop, then reflects the final CRC. The
// table is therefore MSB-first over PRE-REFLECTED bytes:
//   crc = (crc << 8) ^ table[((crc >> 8) ^ reflect(byte)) & 0xFF]
// Equivalent to the bit-wise loop (validated against captured samples).
//
// Thread-safety: the lazy one-time init below is intentionally not atomic.
// ESPHome routes all component calls ({parse_frame, loop, update}) through the
// single main-loop task, so no two tasks can race on `initialized` in practice.
// Keep this function on the main loop task; do not call it from other FreeRTOS
// tasks without first adding a mutex or moving the init to setup().
static const uint16_t *crc16_table() {
  static uint16_t table[256];
  static bool initialized = false;
  if (!initialized) {
    for (int i = 0; i < 256; ++i) {
      uint16_t v = static_cast<uint16_t>(i << 8);
      for (int b = 0; b < 8; ++b) {
        v = (v & 0x8000) ? static_cast<uint16_t>((v << 1) ^ 0x1021) : static_cast<uint16_t>(v << 1);
      }
      table[i] = v;
    }
    initialized = true;
  }
  return table;
}

static uint16_t compute_crc16(const uint8_t *data, size_t len) {
  const uint16_t *const table = crc16_table();
  uint16_t crc = 0xB006;  // init
  for (size_t i = 0; i < len; ++i) {
    uint8_t byte = static_cast<uint8_t>(reflect(data[i], 8));
    crc = static_cast<uint16_t>((crc << 8) ^ table[((crc >> 8) ^ byte) & 0xFF]);
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

  // The first-frame header carries the TOTAL frame count (first frame +
  // continuations), matching the boiler's receive convention.
  std::vector<uint8_t> first_frame;
  first_frame.push_back(static_cast<uint8_t>(((num_cont + 1) << 3) | 0x01));
  first_frame.push_back(msg_header);  // reassembly key
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

  TT_LOGD("[SET] Sent %u CAN frames (msg_header=0x%02X, payload=%zu bytes)", 1 + num_cont, msg_header, data.size());
}

void TopTronic::register_input_callbacks() {
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &i : device->inputs) {
      auto *input = i.second;
      auto *canbus = this->canbus_;
      uint32_t can_id = build_can_id(GATEWAY_DEVICE_TYPE | this->device_addr_, this->get_device_id());

      input->add_on_set_callback([canbus, input, can_id](std::vector<uint8_t> data) -> void {
        // send_can_frames handles single-frame (≤8 bytes) and multi-frame (>8 bytes) automatically.
        send_can_frames(canbus, can_id, data);
      });
    }
  }
}

// Request an immediate refresh from every registered sensor by firing its update
// callback (the same path the polling scheduler takes). Writable inputs (number/
// select) follow automatically through the linked sensors set up in link_inputs().
//
// The refresh is THROTTLED: sensors are queued into pending_refresh_ and released
// a few per loop() tick (max_refresh_per_loop_) so a large preset does not saturate
// the 50 kbps bus with a burst of GET frames.
void TopTronic::update_all() {
  if (!this->pending_refresh_.empty()) {
    TT_LOGI("Refresh already in progress (%zu sensors pending), request ignored", this->pending_refresh_.size());
    return;  // a burst is already in progress
  }
  for (const auto &d : this->devices_) {
    auto *device = d.second.get();
    for (const auto &s : device->sensors) {
      this->pending_refresh_.push_back(s.second);
    }
  }
  TT_LOGI("Refresh requested for all registered sensors");
}

// Thread-safe producers. Safe to call from any FreeRTOS task: they only enqueue a
// command (non-blocking). The main loop task drains the queue in loop() and performs
// the actual work, so component state is never touched from other tasks.
void TopTronic::request_refresh() {
  Command cmd = Command::Refresh;
  if (this->cmd_queue_ != nullptr && xQueueSend(this->cmd_queue_, &cmd, 0) != pdTRUE) {
    TT_LOGD("Command queue full — refresh request dropped");
  }
}

void TopTronic::request_pause() {
  Command cmd = Command::Pause;
  if (this->cmd_queue_ != nullptr && xQueueSend(this->cmd_queue_, &cmd, 0) != pdTRUE) {
    TT_LOGD("Command queue full — pause request dropped");
  }
}

void TopTronic::request_resume() {
  Command cmd = Command::Resume;
  if (this->cmd_queue_ != nullptr && xQueueSend(this->cmd_queue_, &cmd, 0) != pdTRUE) {
    TT_LOGD("Command queue full — resume request dropped");
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
      if (input_base->type() == BUTTON) {
        continue;  // buttons are fire-and-forget — no linked sensor to sync
      }
      auto *sensor_base = this->get_sensor(this->get_device_id(), input_base->get_id());
      if (sensor_base == nullptr) {
        TT_LOGD("Input 0x%08X has no matching sensor — sync skipped", (unsigned) input_base->get_id());
        continue;
      }
      if (sensor_base->type() == SENSOR) {
#if defined(USE_SENSOR) && defined(USE_NUMBER)
        auto *sensor = static_cast<TopTronicSensor *>(sensor_base);
        auto *input = static_cast<TopTronicNumber *>(input_base);
        sensor->add_on_raw_state_callback([input](float state) -> void {
          float divider = input->get_multiplier();
          input->publish_state(state / divider);
        });
#endif  // USE_SENSOR && USE_NUMBER
      } else if (sensor_base->type() == TEXTSENSOR) {
#if defined(USE_TEXT_SENSOR) && defined(USE_SELECT)
        auto *sensor = static_cast<TopTronicTextSensor *>(sensor_base);
        auto *input = static_cast<TopTronicSelect *>(input_base);
        sensor->add_on_raw_state_callback([input](std::string state) -> void { input->publish_state(state); });
#endif  // USE_TEXT_SENSOR && USE_SELECT
      }
    }
  }
}

void TopTronic::setup() {
  this->link_inputs();
  this->register_sensor_callbacks();
  this->register_input_callbacks();

  // One-shot full refresh shortly after boot (configurable, default 30 s, 0 = off).
  // Fires on the ESPHome loop task via the scheduler — non-blocking and thread-safe.
  if (this->boot_refresh_delay_ms_ != 0) {
    this->set_timeout("update_all_initial", this->boot_refresh_delay_ms_, [this]() { this->update_all(); });
  }

  // Producer/consumer bridge for commands issued from other FreeRTOS tasks.
  // Producers only enqueue; the main loop task drains and executes in loop().
  this->cmd_queue_ = xQueueCreate(8, sizeof(Command));

  // Register with the CAN bus so all received frames are routed to parse_frame().
  this->canbus_->add_callback([this](uint32_t can_id, bool, bool rtr, const std::vector<uint8_t> &data) {
    this->parse_frame(data, can_id, rtr);
  });

  // Deduplicated optional debug logging (candump / find can_id). Only the first
  // hub installs this callback — with multiple hubs every hub receives every
  // frame anyway, so logging from each hub's parse_frame() would print N copies.
  // The callback is a no-op unless a debug mode was enabled via cycle_debug_mode().
  if (!s_debug_callback_registered) {
    s_debug_callback_registered = true;
    this->canbus_->add_callback([](uint32_t can_id, bool, bool, const std::vector<uint8_t> &data) {
      debug_log_frame(data, can_id);
    });
  }
}

void TopTronic::loop() {
  // Drain cross-task commands first (non-blocking), so requests issued from other
  // FreeRTOS tasks are serviced on the main loop task — keeping all component state
  // single-threaded (the ESPHome model). Duplicate commands in one drain cycle are
  // coalesced into a single action; the queue itself caps backlog, and the overflow
  // is logged by the producers. Nothing here blocks.
  bool handled_refresh = false;
  bool handled_pause = false;
  bool handled_resume = false;
  Command cmd;
  while (this->cmd_queue_ != nullptr && xQueueReceive(this->cmd_queue_, &cmd, 0) == pdTRUE) {
    switch (cmd) {
      case Command::Refresh:
        if (!handled_refresh) {
          this->update_all();
          handled_refresh = true;
        }
        break;
      case Command::Pause:
        if (!handled_pause) {
          this->pause();
          handled_pause = true;
        }
        break;
      case Command::Resume:
        if (!handled_resume) {
          this->resume();
          handled_resume = true;
        }
        break;
    }
  }

  // Throttled refresh burst: release at most this->max_refresh_per_loop_ sensors per tick.
  size_t sent = 0;
  while (!this->pending_refresh_.empty() && sent < this->max_refresh_per_loop_) {
    TopTronicBase *sensor = this->pending_refresh_.front();
    this->pending_refresh_.pop_front();
    sensor->update();
    ++sent;
  }

  // Periodically evict stale multi-frame reassembly buffers so a lost fragment (or a
  // device going offline mid-message) cannot pin an entry forever. The map is tiny
  // (capped at this->max_pending_messages_), so the sweep is throttled to avoid per-loop work.
  const uint32_t now = millis();
  if (now - this->last_cleanup_ms_ < this->cleanup_interval_ms_)
    return;
  this->last_cleanup_ms_ = now;

  for (auto it = this->pending_messages_.begin(); it != this->pending_messages_.end();) {
    if (now - it->second.last_update_ms > this->max_pending_age_ms_) {
      TT_LOGD("Expiring stale pending message 0x%08X (%zu bytes, %u frames remaining)", (unsigned int) it->first,
              it->second.data.size(), it->second.remaining_frames);
      it = this->pending_messages_.erase(it);
    } else {
      ++it;
    }
  }
}

void TopTronic::on_shutdown() {
  // Free the command bridge queue created in setup().
  if (this->cmd_queue_ != nullptr) {
    vQueueDelete(this->cmd_queue_);
    this->cmd_queue_ = nullptr;
  }
}

void TopTronic::dump_config() {
  size_t sensor_count = 0;
  size_t input_count = 0;
  for (const auto &d : this->devices_) {
    sensor_count += d.second->sensors.size();
    input_count += d.second->inputs.size();
  }
  ESP_LOGCONFIG(TAG, "TopTronic:");
  ESP_LOGCONFIG(TAG, "  Device type: 0x%04X, device address: 0x%02X", this->device_type_, this->device_addr_);
  ESP_LOGCONFIG(TAG, "  Devices: %u, sensors: %u, inputs: %u", (unsigned) this->devices_.size(),
                (unsigned) sensor_count, (unsigned) input_count);
  ESP_LOGCONFIG(TAG, "  Boot refresh delay: %u ms", (unsigned) this->boot_refresh_delay_ms_);
}

static void log_response_frame(const uint8_t *data, size_t len, uint32_t can_id, const std::string &sensor_name) {
  TT_LOGD("[RES] Can-ID: 0x%08X, Sensor: %s, Data: 0x%s", (unsigned int) can_id, sensor_name.c_str(),
          hex_str(data, len).c_str());
}

// Optional per-frame debug logging (canbus.yaml candump / Find can_id blocks).
// Registered exactly ONCE across all hubs (build-wide s_debug_mode/s_debug_callback_registered);
// called from a dedicated canbus callback, not from parse_frame(), so a frame is
// logged once instead of once per hub. Modes:
//   CANDUMP      — log every frame as "0x%08X : %02X %02X ..."
//   FIND_CAN_ID  — log only frames whose data[1] is a 0x42 response or 0x40 request
// Uses the same tags as the old canbus.yaml debug blocks (candump / can_id_find).
static void debug_log_frame(const std::vector<uint8_t> &data, uint32_t can_id) {
  switch (s_debug_mode) {
    case DEBUG_MODE_CANDUMP: {
      std::string line;
      line.reserve(data.size() * 3);
      for (size_t i = 0; i < data.size(); ++i) {
        char tmp[4];
        snprintf(tmp, sizeof(tmp), "%02X ", static_cast<unsigned int>(data[i]));
        line += tmp;
      }
      ESP_LOGI("candump", "0x%08X : %s", (unsigned int) can_id, line.c_str());
      break;
    }
    case DEBUG_MODE_FIND_CAN_ID:
      if (data.size() >= 2) {
        if (data[1] == RESPONSE) {
          // Logged with the toptronic tag at WARN so the message also reaches the
          // "main logs" text sensor via the logger.on_message WARN trigger.
          ESP_LOGW(TAG, "Find can_id: response frame, node 0x%03X (CAN-ID 0x%08X)", (unsigned) ((can_id >> 11) & 0x7FF),
                   (unsigned) can_id);
        } else if (data[1] == GET_REQ) {
          ESP_LOGW(TAG, "Find can_id: request frame, node 0x%03X (CAN-ID 0x%08X)", (unsigned) ((can_id >> 11) & 0x7FF),
                   (unsigned) can_id);
        }
      }
      break;
    default:
      break;
  }
}

void TopTronic::cycle_debug_mode() {
  switch (s_debug_mode) {
    case DEBUG_MODE_OFF:
      s_debug_mode = DEBUG_MODE_CANDUMP;
      ESP_LOGW(TAG, "Debug frame logging CANDUMP enabled — logs every CAN frame; high bus/log latency. "
                    "Disable after use (press the button again), never leave enabled permanently.");
      break;
    case DEBUG_MODE_CANDUMP:
      s_debug_mode = DEBUG_MODE_FIND_CAN_ID;
      ESP_LOGW(TAG, "Debug frame logging FIND CAN-ID enabled — logs only 0x42/0x40 frames. "
                    "Disable after use (press the button again), never leave enabled permanently.");
      break;
    default:
      s_debug_mode = DEBUG_MODE_OFF;
      ESP_LOGI(TAG, "Debug frame logging disabled");
      break;
  }
}

void TopTronic::set_debug_mode(uint8_t mode) {
  if (mode > DEBUG_MODE_FIND_CAN_ID)
    mode = DEBUG_MODE_OFF;
  s_debug_mode = static_cast<DebugMode>(mode);
}

uint8_t TopTronic::get_debug_mode() { return static_cast<uint8_t>(s_debug_mode); }

// Handle a raw CAN frame from the bus.
//
// The TopTronic protocol uses two CAN ID ranges:
//   msg_id == 0x1F  →  start-of-message frame
//   other           →  continuation frame for a multi-frame message
//
// Short messages (msg_len == 0) fit in one frame and are dispatched immediately.
// Longer messages are split into multiple CAN frames and reassembled in pending_messages_
// using (source_device_id << 8 | msg_header) as the reassembly key. Once the expected
// number of continuation frames has arrived the message is dispatched.
void TopTronic::parse_frame(const std::vector<uint8_t> &data, uint32_t can_id, bool remote_transmission_request) {
  if (this->paused_) {
    return;  // OTA in progress — drop frames to keep the main loop and logging free
  }

  uint8_t msg_id = can_id >> 24;
  uint32_t device_id = (can_id >> 11) & 0x7FF;

  if (msg_id == 0x1f) {
    // First frame of a message. data[0] upper 5 bits = number of remaining frames.
    if (data.size() < 2) {
      TT_LOGW("Dropping malformed start frame (%zu bytes)", data.size());
      return;
    }
    uint8_t num_remaining = data[0] >> 3;
    // The first-frame header holds the TOTAL frame count (first frame +
    // continuations). A legit U32/S32 response uses 2, S64 uses 3 — anything
    // claiming more than this->max_frames_per_message_ is a corrupted header. Reject it
    // immediately instead of reserving buffer space for up to 31 continuations.
    if (num_remaining > this->max_frames_per_message_) {
      TT_LOGW("Dropping start frame with implausible frame count %u (header 0x%02X)", num_remaining, data[0]);
      return;
    }
    if (num_remaining == 0) {
      // Single-frame message: strip the length byte and dispatch directly.
      this->interpret_message(data.data() + 1, data.size() - 1, can_id, remote_transmission_request);
    } else {
      // Multi-frame message: save the first fragment and wait for the rest.
      uint8_t msg_header = data[1];  // reassembly key shared across all frames of this message
      uint32_t header_key = (device_id << 8) | msg_header;
      TT_LOGD("     - Start of message with id: %d with length %d", msg_header, num_remaining);
      if (this->pending_messages_.size() >= this->max_pending_messages_ &&
          this->pending_messages_.find(header_key) == this->pending_messages_.end()) {
        // Buffer full: evict the SINGLE oldest entry (LRU) instead of clearing all
        // in-progress reassemblies. On a multi-hub bus every hub reassembles every
        // device's frames, so a full clear() would destroy the other hubs' pending
        // messages too — turning a full-buffer moment into lost responses until the
        // next 30 s poll. This map is capped and tiny (32 entries), so the linear
        // oldest-find is cheap and only runs on the full-buffer path.
        uint32_t oldest_key = this->pending_messages_.begin()->first;
        uint32_t oldest_ms = this->pending_messages_.begin()->second.last_update_ms;
        for (auto pit = this->pending_messages_.begin(); pit != this->pending_messages_.end(); ++pit) {
          if (pit->second.last_update_ms < oldest_ms) {
            oldest_key = pit->first;
            oldest_ms = pit->second.last_update_ms;
          }
        }
        TT_LOGW("Pending message buffer full (%zu entries), evicting oldest 0x%08X", this->pending_messages_.size(),
                (unsigned int) oldest_key);
        this->pending_messages_.erase(oldest_key);
      }

      PendingMessage pending;
      pending.data.assign(data.begin() + 2, data.end());
      // Pre-allocate: each continuation frame carries at most 7 payload bytes (8 - header byte).
      pending.data.reserve(static_cast<size_t>(num_remaining) * 7);
      // data[0]>>3 is the TOTAL frame count (first frame + continuations), so
      // only num_remaining - 1 continuation frames are expected. Verified against
      // captured bus traffic (command 0x42 responses to register 0x74).
      pending.remaining_frames = num_remaining - 1;
      pending.last_update_ms = millis();
      this->pending_messages_[header_key] = std::move(pending);
    }
  } else {
    // Continuation frame: append payload to the in-progress message.
    if (data.size() < 2) {
      TT_LOGW("Dropping malformed continuation frame (%zu bytes)", data.size());
      return;
    }
    uint8_t msg_header = data[0];
    uint32_t header_key = (device_id << 8) | msg_header;
    auto it = this->pending_messages_.find(header_key);
    if (it == this->pending_messages_.end()) {
      // Continuation for an unknown/expired message (evicted, purged, or the start
      // frame never arrived). Logged at DEBUG so lost reassemblies are visible.
      TT_LOGD("[DROP] Continuation for unknown/expired message (node 0x%03X, header 0x%02X)",
              (unsigned) device_id, msg_header);
      return;
    }
    PendingMessage &pending = it->second;
    if (pending.remaining_frames == 0) {
      // Duplicate/extra continuation for an already-complete message — discard.
      TT_LOGD("[DROP] Extra continuation for complete message (node 0x%03X, header 0x%02X)",
              (unsigned) device_id, msg_header);
      this->pending_messages_.erase(it);
      return;
    }
    TT_LOGD("     - Part of message with id: %d with remaining length %d", msg_header,
            pending.remaining_frames - 1);
    pending.data.insert(pending.data.end(), data.begin() + 1, data.end());
    pending.last_update_ms = millis();
    pending.remaining_frames--;

    if (pending.remaining_frames == 0) {
      const size_t msg_len = pending.data.size();
      if (msg_len < MIN_MESSAGE_LEN + 2) {
        TT_LOGW("Reassembled message too short for CRC (%zu bytes)", msg_len);
        this->pending_messages_.erase(it);
        return;
      }

      const uint8_t *msg = pending.data.data();
      uint16_t received_crc = (msg[msg_len - 2] << 8) | msg[msg_len - 1];
      uint16_t computed_crc = compute_crc16(msg, msg_len - 2);

      if (received_crc != computed_crc) {
        TT_LOGW("CRC check failed! Recv: 0x%04X, Comp: 0x%04X", received_crc, computed_crc);
        this->pending_messages_.erase(it);
        return;
      }

      // Dispatch first, then free the reassembly buffer (msg points into pending.data).
      this->interpret_message(msg, msg_len - 2, can_id, remote_transmission_request);
      this->pending_messages_.erase(it);
    }
  }
}

// Dispatch a fully reassembled TopTronic message.
//
// Message byte layout (after the CAN framing bytes are stripped):
//   [0]   command byte  0x40 GET, 0x46 SET, 0x42/0x56 RESPONSE
//   [1]   function_group
//   [2]   function_number
//   [3]   datapoint high byte
//   [4]   datapoint low byte
//   [5..] value payload (0x42). 0x56 inserts 2 bytes (0x80 0x00) at [5..6],
//         so its value starts at [7].
void TopTronic::interpret_message(const uint8_t *data, size_t len, uint32_t can_id, bool remote_transmission_request) {
  if (len < MIN_MESSAGE_LEN) {
    TT_LOGD("Message too short (%u bytes), ignoring", (unsigned) len);
    return;
  }

  // Ignore outgoing GET/SET requests that we echoed ourselves — nothing to update.
  if (data[0] == GET_REQ) {
    TT_LOGD("[GET] Can-ID: 0x%08X, Data: 0x%s", (unsigned int) can_id, hex_str(data, len).c_str());
    return;
  }

  if (data[0] == SET_REQ) {
    TT_LOGD("[SET] Can-ID: 0x%08X, Data: 0x%s", (unsigned int) can_id, hex_str(data, len).c_str());
    return;
  }

  bool is_response = (data[0] == RESPONSE || data[0] == RESPONSE_EXT);
  if (!is_response) {
    TT_LOGD("[UNK] Can-ID: 0x%08X, Data: 0x%s", (unsigned int) can_id, hex_str(data, len).c_str());
    return;
  }
  // 0x56 inserts 2 header bytes (0x80 0x00) between the datapoint and the value.
  const size_t value_off = (data[0] == RESPONSE_EXT) ? 7 : 5;
  if (len < value_off) {
    TT_LOGD("Response without value bytes (%u bytes), ignoring", (unsigned) len);
    return;
  }

  // The sender node ID sits in bits 21-11 of the CAN ID.
  uint32_t rx_device_id = (can_id >> 11) & 0x7FF;

  auto device_it = this->devices_.find(rx_device_id);
  if (device_it == this->devices_.end()) {
    // Message from a device we have no entities registered for. Logged at DEBUG
    // so unknown node ids (e.g. a misconfigured device_type tag) are visible
    // instead of silently dropping every frame from that device.
    TT_LOGD("[DROP] No device registered for node id 0x%03X, cmd=0x%02X fg=%u fn=%u dp_hi=0x%02X dp_lo=0x%02X",
            (unsigned) rx_device_id, data[0], data[1], data[2], data[3], data[4]);
    return;
  }
  TopTronicDevice *device = device_it->second.get();

  // Reconstruct the sensor lookup key from the protocol fields in the response.
  uint32_t datapoint = data[4] + (data[3] << 8);
  uint32_t id = data[1]           // function_group
                + (data[2] << 8)  // function_number
                + (datapoint << 16);

  auto sensor_it = device->sensors.find(id);
  if (sensor_it == device->sensors.end()) {
    // Unregistered datapoint for a known device. Logged at DEBUG so preset key
    // mismatches (fg/fn/dp vs. what the device actually emits) are visible
    // instead of silently dropping the response.
    TT_LOGD("[DROP] No sensor for key 0x%08X on node 0x%03X (fg=%u fn=%u dp=%u)",
            (unsigned) id, (unsigned) rx_device_id, data[1], data[2], (unsigned) datapoint);
    return;
  }
  TopTronicBase *sensor_base = sensor_it->second;

  // Downcast to the concrete type and publish the decoded value.
  // data[value_off..] contains the raw value bytes.
#ifdef USE_SENSOR
  if (sensor_base->type() == SENSOR) {
    auto *sensor = static_cast<TopTronicSensor *>(sensor_base);
    float value = sensor->parse_value(data + value_off, len - value_off);
    sensor->publish_state(value);
    log_response_frame(data, len, can_id, sensor->get_name());
  }
#endif
#ifdef USE_TEXT_SENSOR
  if (sensor_base->type() == TEXTSENSOR) {
    auto *sensor = static_cast<TopTronicTextSensor *>(sensor_base);
    std::string value = sensor->parse_value(data + value_off, len - value_off);
    sensor->publish_state(value);
    log_response_frame(data, len, can_id, sensor->get_name());
  }
#endif
}

}  // namespace esphome::toptronic