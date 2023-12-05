
#include "esphome/core/component.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/canbus/canbus.h"

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

class TopTronicSensor: public sensor::Sensor {
   public:
    // explicit TopTronicSensor(TopTronic *parent): parent_(parent){};

    void set_device_type(uint8_t device_type) { device_type_ = device_type; }
    void set_device_addr(uint8_t device_addr) { device_addr_ = device_addr; }

    void set_function_group(uint8_t function_group) { function_group_ = function_group; }
    void set_function_number(uint8_t function_number) { function_number_ = function_number; }
    void set_datapoint(uint16_t datapoint) { datapoint_ = datapoint; }
    void set_type(TypeName type) { type_ = type; }

    float parse_value(std::vector<uint8_t> value);
    uint32_t get_id();
    uint32_t get_can_id();

    std::vector<uint8_t> request_data();

   protected:
    // TopTronic *parent_;
    uint8_t device_type_;
    uint8_t device_addr_;

    uint8_t function_group_;
    uint8_t function_number_;
    uint16_t datapoint_;
    TypeName type_;
};

class TopTronicDevice {
   public:
    std::map<uint32_t, TopTronicSensor*> sensors;
};

class TopTronic : public Component {
   public:
    explicit TopTronic(canbus::Canbus *canbus): canbus_(canbus){};

    void add_sensor(TopTronicSensor *sensor);
    void parse_frame(std::vector<uint8_t> data, uint32_t can_id, bool remote_transmission_request);

    void setup() override;
    void loop() override;
    void dump_config() override;

   protected:
    TopTronicDevice* get_or_create_device(uint32_t can_id);

    canbus::Canbus *canbus_;
    std::map<uint32_t, TopTronicDevice*> devices_;
    
    // uint32_t int_id_(std::string id);
};

}  // namespace toptronic
}  // namespace esphome
