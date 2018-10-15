import RPi.GPIO as GPIO
import Adafruit_DHT

from flask import Flask, render_template, url_for, copy_current_request_context
from flask_socketio import SocketIO, emit

from luma.led_matrix.device import max7219
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.core.virtual import viewport
from luma.core.legacy import text, show_message
from luma.core.legacy.font import proportional, CP437_FONT, TINY_FONT, SINCLAIR_FONT, LCD_FONT

import time
import signal
import sys
import threading
import math
from enum import IntEnum

import logging

import eventlet
eventlet.monkey_patch()


class State(IntEnum):
    DISABLED = -1

    IDLE = 0
    HEATING = 1
    COOLING = 2
    FANS = 3

    SHUTDOWN = 4
    TRANSITION = 5


class Mode(IntEnum):
    COOL = 0
    HEAT = 1
    AUTO = 2
    FAN_ONLY = 3


class FanSpeed(IntEnum):
    LOW = 0
    HIGH = 1
    AUTO = 2


class StateDesired(IntEnum):
    ACTIVE = 0
    DISABLED = 1


class CircularBuffer:
    size = 0
    data = []
    index = 0

    def __init__(self, size):
        self.size = size
        self.data = [None] * size
        self.index = 0

    def write(self, value):
        self.data[self.index] = value
        self.index = self.index + 1
        if self.index >= self.size:
            self.index = 0

    def read(self):
        return self.data[self.index - 1]

    def read_all(self):
        return [x for x in self.data if x]


class System:
    enabled = False

    system_state = State.IDLE
    system_mode = Mode.AUTO
    fan_mode = FanSpeed.LOW
    system_state_desired = StateDesired.DISABLED

    current_temp = 0.0
    instant_temp = 0.0
    desired_temp = 75.0

    temps = CircularBuffer(60)
    humid = CircularBuffer(60)


    def __init__(self):
        self.enabled = False

        self.system_state = State.DISABLED
        self.system_mode = Mode.AUTO
        self.fan_mode = FanSpeed.LOW
        self.system_state_desired = StateDesired.DISABLED

        self.current_temp = 0.0
        self.instant_temp = 0.0
        self.desired_temp = 75.0

        self.temps = CircularBuffer(60)
        self.humid = CircularBuffer(60)

    def __str__(self):
        return str(self.enabled) + "\n\t" + str(self.system_state) + "\t" + str(self.system_mode) + "\t" + str(self.fan_mode) + "\n\t" + str(self.current_temp) + "\t" + str(self.instant_temp) + "\t" + str(self.desired_temp)


# Relay pins (not GPIO pins)
#              1   2   3   4   5   6   7   8
relay_pins = [36, 11, 13, 15, 16, 18, 22, 31]

# This table lists wires, meaning, and color
# Wire |  Purpose  |  Color
# -------------------------
#   C  |  Common   |  Blue
#   R  |  24 Volt  |  Green
#   A  |  ??????   |  Yellow
#  RT  |  ??????   |  Orange
#  RT  |  ??????   |  Red
#  G1  | Fan Low   |  Dark Grey
#  G2  | Fan High  |  Black
#  Y1  |  Cooling  |  White
#  W1  |  Heating  |  Grey
#  W2  |  ??????   |
#   O  | Rev Valve |  Purple
fan_low_relay  = 36
fan_high_relay = 11

cooling_relay = 13
heating_relay = 15

reverse_relay = 16

temp_pin = 12
serial = None
device = None

system = System()
lock = threading.Lock()

app = Flask(__name__)
socketio = SocketIO(app)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Just turn on the fans
def enable_fans_only(fan_speed_high=False):
    if fan_speed_high:
        GPIO.output(fan_high_relay, False)
    else:
        GPIO.output(fan_low_relay, False)

# Turn off the fans
def disable_fans_only(fan_speed_high=False):
    if fan_speed_high:
        GPIO.output(fan_high_relay, True)
    else:
        GPIO.output(fan_low_relay, True)

# To start cooling the room, do the following:
#   1. Activate the fan at the desired speed
#       for at least 30 seconds
#   2. Energize the reversing valve
#   3. Energize the cooling line
# It is critical to note that we MUST cool for at
#   least 4 minutes! This is to prevent compressor
#   and pump damage (rapid cycling add extra wear)
def enable_cooling(fan_speed_high=False):
    global system
    global lock

    # Activate the desired fan. ONLY ACTIVATE ONE
    enable_fans_only(fan_speed_high)

    # Wait for fans
    time.sleep(30)

    # Activate cooling
    GPIO.output(reverse_relay, False)
    GPIO.output(cooling_relay, False)
    lock.acquire()
    system.system_state = State.COOLING
    lock.release()

# To stop cooling the room, do the following:
#   1. De-energize the reversing valve
#   2. De-energize the cooling line
#   1. Activate the fan at the desired speed
#       for at least 90 seconds to cool the
#       compressor and pump
def disable_cooling(fan_speed_high=False):
    global system
    global lock

    # Stop cooling
    GPIO.output(cooling_relay, True)
    GPIO.output(reverse_relay, True)

    # We need to cool down the compressor and pump
    # so run the fans for around a minute
    time.sleep(90)
    # Deactivate the desired fan.
    disable_fans_only(fan_speed_high)
    lock.acquire()
    system.system_state = State.SHUTDOWN
    lock.release()

# To start heating the room, do the following:
#   1. Activate the fan at the desired speed
#       for at least 30 seconds
#   2. Energize the heating line
# It is critical to note that we MUST cool for at
#   least 4 minutes! This is to prevent compressor
#   and pump damage (rapid cycling add extra wear)
def enable_heating(fan_speed_high=False):
    global system
    global lock

    # Activate the desired fan. ONLY ACTIVATE ONE
    enable_fans_only(fan_speed_high)

    # Wait for fans
    time.sleep(30)

    # Activate heating
    GPIO.output(heating_relay, False)
    lock.acquire()
    system.system_state = State.HEATING
    lock.release()

# To stop heating the room, do the following:
#   1. De-energize the heating relay
#   1. Activate the fan at the desired speed
#       for at least 60 seconds to cool the
#       compressor and pump
def disable_heating(fan_speed_high=False):
    global system
    global lock

    # Stop Heating
    GPIO.output(heating_relay, True)

    # We need to cool down the compressor and pump
    # so run the fans for around a minute
    time.sleep(60)
    # Deactivate the desired fan.
    disable_fans_only(fan_speed_high)
    lock.acquire()
    system.system_state = State.SHUTDOWN
    lock.release()

def measure_temp_threaded():
    global system
    global lock

    humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, temp_pin)
    temperature = temperature * 9/5.0 + 32

    lock.acquire()
    system.temps.write(temperature)
    system.humid.write(humidity)
    system.instant_temp = temperature
    lock.release()


    time.sleep(3)
    threading.Thread(target=measure_temp_threaded).start()

def measure_temp():
    global system
    global lock

    print("Measuring temp...")
    humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, temp_pin)
    temperature = temperature * 9/5.0 + 32
    print("Read value of %f with humidity" % (temperature))

    lock.acquire()
    system.temps.write(temperature)
    system.humid.write(humidity)
    system.instant_temp = temperature
    lock.release()

    time.sleep(3)

def init_relays():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BOARD)
    for pin in relay_pins:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

def init_display():
    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=4, block_orientation=-90, rotate=0)
    with canvas(device) as draw:
        text(draw,(0,0), "Hi!", fill="white", font=proportional(SINCLAIR_FONT))
    print("Display Inited..")

def signal_handler(sig, frame):
    for pin in relay_pins:
        GPIO.output(pin, True)
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

def main():
    global app
    global system
    global socketio
    global lock

    time.sleep(3)

    app.config['SECRET_KEY'] = 'secret'
    app.config['DEBUG'] = True

    init_relays()
    measure_temp()
    init_display()

    temps = system.temps.read_all()

    threading.Thread(target=measure_temp_threaded).start()
    curr_temp = reduce(lambda x, y: x + y, temps) / float(len(temps))
    current_time = int(round(time.time() * 1000))

    while True:
        lock.acquire()

        temps = system.temps.read_all()

        previous_time = current_time
        previous_temp = curr_temp
        curr_temp = reduce(lambda x, y: x + y, temps) / float(len(temps))
        current_time = int(round(time.time() * 1000))

        time_diff = ((current_time - previous_time)/1000.0)
        if time_diff == 0:
            time_diff = 1/1000.0
        rate = (curr_temp - previous_temp)/time_diff
        if rate == 0:
            rate = 1/10.0
        system.current_temp = curr_temp
        temp_diff = round(curr_temp - system.desired_temp, 2)

        time_to_temp = int(math.ceil(abs(temp_diff/rate)))/60

        enabled = system.system_state != State.DISABLED
        msg = {'current_temperature': round(curr_temp, 1),
          'enabled': enabled,
          'system_mode': str(system.system_mode),
          'system_state': str(system.system_state),
          'desired_temperature': round(system.desired_temp, 1),
          'time_to_temp': time_to_temp}
        socketio.emit('tempHeartbeat', {'temp': round(curr_temp, 1)})
        socketio.emit('statusHeartbeat', msg)

        print("==============")
        print("Current status: %f, %f=>%f\tLast read val: %f" % (temp_diff, curr_temp, system.desired_temp, system.instant_temp))
        print(system)
        print("==============")

        if system.system_state == State.DISABLED:
            if system.system_state_desired == StateDesired.ACTIVE:
                system.system_state = State.IDLE
        elif system.system_state == State.IDLE:
            if system.system_state_desired == StateDesired.DISABLED:
                system.system_state = State.DISABLED
            elif (temp_diff >= 3.0) and (system.system_mode == Mode.COOL or system.system_mode == Mode.AUTO):
                # Start Cooling
                system.system_state = State.TRANSITION
                threading.Thread(target=enable_cooling).start()
            elif (temp_diff <= -3.0) and (system.system_mode == Mode.HEAT or system.system_mode == Mode.AUTO):
                # Start Heating
                system.system_state = State.TRANSITION
                threading.Thread(target=enable_heating).start()
        elif system.system_state == State.HEATING:
            # Stay in heating until target temp is met OR system is requested for shutdown
            if (abs(temp_diff) < 0.25) or (system.current_temp > system.desired_temp):
                # Start Heating Shutdown because we reached temp
                system.system_state = State.TRANSITION
                threading.Thread(target=disable_heating).start()
            elif system.system_state_desired == StateDesired.DISABLED:
                # Start Heating Shutdown because user shutdown
                system.system_state = State.TRANSITION
                threading.Thread(target=disable_heating).start()
        elif system.system_state == State.COOLING:
            # Stay in cooling until target temp is met OR system is requested for shutdown
            if (abs(temp_diff) < 0.25) or (system.current_temp < system.desired_temp):
                # Start Cooling Shutdown because we reached temp
                system.system_state = State.TRANSITION
                threading.Thread(target=disable_cooling).start()
            elif system.system_state_desired == StateDesired.DISABLED:
                # Start Cooling Shutdown because user shutdown
                system.system_state = State.TRANSITION
                threading.Thread(target=disable_cooling).start()
        elif system.system_state == State.SHUTDOWN:
            system.system_state = State.IDLE
        elif system.system_state == State.TRANSITION:
            pass
        lock.release()

        time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('disable_system')
def disable_system(msg):
    global system
    global lock

    lock.acquire()
    system.system_state_desired = StateDesired.DISABLED
    lock.release()
    print("System disabled")

@socketio.on('enable_system')
def enable_system(msg):
    global system
    global lock

    lock.acquire()
    system.system_state_desired = StateDesired.ACTIVE
    lock.release()
    print("System enabled")

@socketio.on('set_temperature')
def set_temperature(temp):
    global system
    global lock

    print(temp)
    lock.acquire()
    system.desired_temp = int(temp)
    lock.release()

@socketio.on('set_mode')
def set_temperature(mode):
    global system
    global lock

    print("Got Mode: " + str(mode))
    mode = int(mode)
    lock.acquire()
    if mode == 0:
        system.system_mode = Mode.COOL
    elif mode == 1:
        system.system_mode = Mode.HEAT
    elif mode == 2:
        system.system_mode = Mode.AUTO
    else:
        system.system_mode = Mode.FAN_ONLY
    lock.release()

if __name__ == "__main__":
    threading.Thread(target=main).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
