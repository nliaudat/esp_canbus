
#include "esphome/core/component.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/select/select.h"
#include "esphome/components/number/number.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/canbus/canbus.h"
#include "esphome/core/helpers.h"

#include <map>

namespace esphome {
namespace toptronic {

enum TypeName {
    U8,
    U16,
    U32,
    S8,
    S16,
    S32,
    S64,
};

enum SensorType {
    SENSOR,
    TEXTSENSOR,
};

uint32_t build_can_id(uint16_t sender_id, uint16_t receiver_mask);
std::vector<uint8_t> build_get_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint);
std::vector<uint8_t> build_set_request(uint8_t function_group, uint8_t function_number, uint32_t datapoint, std::vector<uint8_t> value);

class TopTronicBase: public PollingComponent {
   public:
    void set_device_type(uint16_t device_type) { device_type_ = device_type; }
    void set_device_addr(uint8_t device_addr) { device_addr_ = device_addr; }

    void set_function_group(uint8_t function_group) { function_group_ = function_group; }
    void set_function_number(uint8_t function_number) { function_number_ = function_number; }
    void set_datapoint(uint16_t datapoint) { datapoint_ = datapoint; }

    uint32_t get_id();
    uint32_t get_device_id();
    std::vector<uint8_t> get_request_data();

    virtual SensorType type() = 0;

    void update() override;
    void add_on_update_callback(std::function<void()> &&callback);
    void add_on_set_callback(std::function<void(std::vector<uint8_t>)> &&callback);

   protected:
    uint16_t device_type_;
    uint8_t device_addr_;

    uint8_t function_group_;
    uint8_t function_number_;
    uint16_t datapoint_;

    CallbackManager<void()> update_callback_;
    CallbackManager<void(std::vector<uint8_t>)> set_callback_; 
};

class TopTronicSensor: public sensor::Sensor, public TopTronicBase {
   public:
    void set_type(TypeName type) { type_ = type; }

    float parse_value(std::vector<uint8_t> value);
    SensorType type() override { return SENSOR; };

   protected:
    TypeName type_;
};

class TopTronicNumber: public number::Number, public TopTronicBase {
   public:    
    void set_type(TypeName type) { type_ = type; }
    void set_multiplier(float multiplier) { multiplier_ = multiplier; }
    float get_multiplier() { return multiplier_; }
    SensorType type() override { return SENSOR; };
    void control(float value) override;

   protected:
    TypeName type_;
    float multiplier_ = 1;
};

class TopTronicTextSensor: public text_sensor::TextSensor, public TopTronicBase {
   public:
    std::string parse_value(std::vector<uint8_t> value);
    SensorType type() override { return TEXTSENSOR; };

    void add_option(uint8_t value, std::string text) {
        toText_[value] = text;
        toValue_[text] = value;
    }

   protected:
    std::map<uint8_t, std::string> toText_;
    std::map<std::string, uint8_t> toValue_;
};

class TopTronicSelect: public select::Select, public TopTronicBase {
   public:
    SensorType type() override { return TEXTSENSOR; };

    void add_option(uint8_t value, std::string text) {
        toText_[value] = text;
        toValue_[text] = value;
    }

   protected:
    std::map<uint8_t, std::string> toText_;
    std::map<std::string, uint8_t> toValue_;

    void control(const std::string &value) override;
};

class TopTronicDevice {
   public:
    std::map<uint32_t, TopTronicBase*> sensors;
    std::map<uint32_t, TopTronicBase*> inputs;
};

class TopTronic : public Component {
   public:
    explicit TopTronic(canbus::Canbus *canbus): canbus_(canbus){};

    void add_sensor(TopTronicBase *sensor);
    void add_input(TopTronicBase *input);
    void parse_frame(std::vector<uint8_t> data, uint32_t can_id, bool remote_transmission_request);
    void register_sensor_callbacks();
    void register_input_callbacks();
    void set_device_type(uint16_t device_type) { device_type_ = device_type; }
    void set_device_addr(uint8_t device_addr) { device_addr_ = device_addr; }

    void setup() override;
    void loop() override;
    void dump_config() override;

   protected:
    TopTronicDevice* get_or_create_device(uint32_t can_id);
    void link_inputs();
    TopTronicBase* get_sensor(uint32_t device_id, uint32_t sensor_id);
    void interpret_message(std::vector<uint8_t> data, uint32_t can_id, bool remote_transmission_request);

    canbus::Canbus *canbus_;
    std::map<uint32_t, TopTronicDevice*> devices_;
    // msg_header -> (data, number of pending messages)
    std::map<uint8_t, std::pair<std::vector<uint8_t>, uint8_t>> pending_messages_;

    uint16_t device_type_;
    uint8_t device_addr_;
};

}  // namespace toptronic
}  // namespace esphome
