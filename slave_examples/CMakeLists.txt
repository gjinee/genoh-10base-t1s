cmake_minimum_required(VERSION 3.16)
project(zenoh_t1s_slave_examples C)

# Find zenoh-pico
# Assumes zenoh-pico is installed via:
#   git clone https://github.com/eclipse-zenoh/zenoh-pico.git
#   cd zenoh-pico && mkdir build && cd build
#   cmake .. -DCMAKE_BUILD_TYPE=Release -DZ_FEATURE_LIVELINESS=ON
#   make && sudo make install
find_package(zenohpico REQUIRED)

# Build flags for 10BASE-T1S:
#   Z_FEATURE_LINK_TCP=ON      — TCP transport to zenohd router
#   Z_FEATURE_LIVELINESS=ON    — Node online/offline detection
#   Z_FEATURE_RAWETH_TRANSPORT=OFF — Not used (zenohd doesn't support raweth)

# Sensor node example
add_executable(sensor_node sensor_node.c)
target_link_libraries(sensor_node zenohpico::lib)

# Actuator node example
add_executable(actuator_node actuator_node.c)
target_link_libraries(actuator_node zenohpico::lib)
