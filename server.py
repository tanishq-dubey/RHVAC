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
    OFF = 0
    HEATING = 1
    COOLING = 2
    FAN_ONLY = 3
    SHUTDOWN = 4

class Mode(IntEnum):
    COOL = 0
    HEAT = 1
    AUTO = 2
    FAN_ONLY = 3

class FanSpeed(IntEnum):
    LOW = 0
    HIGH = 1

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
    current_state = State.OFF
    desired_mode = Mode.AUTO
    fan_mode = FanSpeed.LOW
    current_temperature = 0.0
    instant_temperature = 0.0
    desired_temperature = 75.0

    temps = CircularBuffer(60)
    humid = CircularBuffer(60)

    def __init__(self):
        self.enabled = False
        self.current_state = State.OFF
        self.desired_mode = Mode.AUTO
        self.fan_mode = FanSpeed.LOW
        self.current_temperature = 0.0
        self.instant_temperature = 0.0
        self.desired_temperature = 75.0

        self.temps = CircularBuffer(60)
        self.humid = CircularBuffer(60)

    def __str__(self):
        return str(self.enabled) + "\n\t" + str(self.current_state) + "\t" + str(self.desired_mode) + "\t" + str(self.fan_mode) + "\n\t" + str(self.current_temperature) + "\t" + str(self.instant_temperature) + "\t" + str(self.desired_temperature)


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

    lock.acquire()
    system.current_state = State.COOLING
    lock.release()
    # Activate the desired fan. ONLY ACTIVATE ONE
    enable_fans_only(fan_speed_high)

    # Wait for fans
    time.sleep(30)

    # Activate cooling
    GPIO.output(reverse_relay, False)
    GPIO.output(cooling_relay, False)

# To stop cooling the room, do the following:
#   1. De-energize the reversing valve
#   2. De-energize the cooling line
#   1. Activate the fan at the desired speed
#       for at least 90 seconds to cool the
#       compressor and pump
def disable_cooling(fan_speed_high=False):
    global system
    global lock

    lock.acquire()
    system.current_state = State.SHUTDOWN
    lock.release()

    # Stop cooling
    GPIO.output(cooling_relay, True)
    GPIO.output(reverse_relay, True)

    # We need to cool down the compressor and pump
    # so run the fans for around a minute
    time.sleep(90)
    # Deactivate the desired fan.
    disable_fans_only(fan_speed_high)
    lock.acquire()
    system.current_state = State.OFF
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

    lock.acquire()
    system.current_state = State.HEATING
    lock.release()
    # Activate the desired fan. ONLY ACTIVATE ONE
    enable_fans_only(fan_speed_high)

    # Wait for fans
    time.sleep(30)

    # Activate heating
    GPIO.output(heating_relay, False)

# To stop heating the room, do the following:
#   1. De-energize the heating relay
#   1. Activate the fan at the desired speed
#       for at least 60 seconds to cool the
#       compressor and pump
def disable_heating(fan_speed_high=False):
    global system
    global lock

    lock.acquire()
    system.current_state = State.SHUTDOWN
    lock.release()

    # Stop Heating
    GPIO.output(heating_relay, True)

    # We need to cool down the compressor and pump
    # so run the fans for around a minute
    time.sleep(60)
    # Deactivate the desired fan.
    disable_fans_only(fan_speed_high)
    lock.acquire()
    system.current_state = State.OFF
    lock.release()

def measure_temp_threaded():
    global system
    global lock

    humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, temp_pin)
    temperature = temperature * 9/5.0 + 32

    lock.acquire()
    system.temps.write(temperature)
    system.humid.write(humidity)
    system.instant_temperature = temperature
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
    system.instant_temperature = temperature
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

    threading.Thread(target=measure_temp_threaded).start()
    curr_temp = 75
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
            time_diff = 1
        rate = (curr_temp - previous_temp)/time_diff
        if rate == 0:
            rate = 1
        system.current_temperature = curr_temp
        diff = round(curr_temp - system.desired_temperature, 2)

        time_to_temp = int(math.ceil(diff/rate))

        msg = {'current_temperature': round(curr_temp, 1),
          'enabled': system.enabled,
          'desired_mode': str(system.desired_mode),
          'current_state': str(system.current_state),
          'desired_temperature': round(system.desired_temperature, 1),
          'time_to_temp': time_to_temp}
        socketio.emit('tempHeartbeat', {'temp': round(curr_temp, 1)})
        socketio.emit('statusHeartbeat', msg)

        print("==============")
        print(id(system))
        print("Current status: %f, %f=>%f\tLast read val: %f" % (diff, curr_temp, system.desired_temperature, system.instant_temperature))
        print(system)
        print("==============")

        if system.enabled:
            if (diff > 3.0) and (system.current_state == State.OFF) and (system.desired_mode == Mode.AUTO or system.desired_mode == Mode.COOL):
                print("Enable cooling: %f, %f=>%f" % (diff, curr_temp, system.desired_temperature))
                threading.Thread(target=enable_cooling).start()
            elif (diff < -3.0) and (system.current_state == State.OFF) and (system.desired_mode == Mode.AUTO or system.desired_mode == Mode.HEAT):
                print("Enable Heating: %f, %f=>%f" % (diff, curr_temp, system.desired_temperature))
                threading.Thread(target=enable_heating).start()
            elif (system.current_state == State.COOLING) and ((curr_temp < system.desired_temperature) or abs(diff) < 0.5):
                print("Turning off HVAC: %f, %f=>%f" % (diff, curr_temp, system.desired_temperature))
                threading.Thread(target=disable_cooling).start()
            elif (system.current_state == State.HEATING) and ((curr_temp > system.desired_temperature) or abs(diff) < 0.5):
                print("Turning off HVAC: %f, %f=>%f" % (diff, curr_temp, system.desired_temperature))
                threading.Thread(target=disable_heating).start()
        lock.release()

        time.sleep(4)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('disable_system')
def disable_system(msg):
    global system
    global lock

    lock.acquire()
    if system.enabled:
        if system.current_state == State.COOLING:
            threading.Thread(target=disable_cooling).start()
        elif system.current_state == State.HEATING:
            threading.Thread(target=disable_heating).start()
        else:
            disable_fans_only()

    system.enabled = False
    lock.release()
    print("System disabled")

@socketio.on('enable_system')
def enable_system(msg):
    global system
    global lock

    lock.acquire()
    system.enabled = True
    lock.release()
    print("System enabled")

@socketio.on('set_temperature')
def set_temperature(temp):
    global system
    global lock

    print(temp)
    lock.acquire()
    system.desired_temperature = int(temp)
    lock.release()

@socketio.on('set_mode')
def set_temperature(mode):
    global system
    global lock

    print("Got Mode: " + str(mode))
    mode = int(mode)
    lock.acquire()
    if mode == 0:
        system.desired_mode = Mode.COOL
    elif mode == 1:
        system.desired_mode = Mode.HEAT
    elif mode == 2:
        system.desired_mode = Mode.AUTO
    else:
        system.desired_mode = Mode.FAN_ONLY
    lock.release()

if __name__ == "__main__":
    threading.Thread(target=main).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
