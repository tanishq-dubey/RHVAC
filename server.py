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
from enum import Enum

class State(Enum):
    OFF = 0
    HEATING = 1
    COOLING = 2
    FAN_ONLY = 3

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

ideal_temp = 72.0

c_buf = CircularBuffer(60)

c_state = State.OFF

app = Flask(__name__)


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
    global c_state
    c_state = State.COOLING
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
    global c_state
    # Stop cooling
    GPIO.output(cooling_relay, True)
    GPIO.output(reverse_relay, True)

    # We need to cool down the compressor and pump
    # so run the fans for around a minute
    time.sleep(90)
    # Deactivate the desired fan.
    disable_fans_only(fan_speed_high)
    c_state = State.OFF

# To start heating the room, do the following:
#   1. Activate the fan at the desired speed
#       for at least 30 seconds
#   2. Energize the heating line
# It is critical to note that we MUST cool for at
#   least 4 minutes! This is to prevent compressor
#   and pump damage (rapid cycling add extra wear)
def enable_heating(fan_speed_high=False):
    global c_state
    c_state = State.HEATING
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
    global c_state
    # Stop Heating
    GPIO.output(heating_relay, True)

    # We need to cool down the compressor and pump
    # so run the fans for around a minute
    time.sleep(60)
    # Deactivate the desired fan.
    disable_fans_only(fan_speed_high)
    c_state = State.OFF

def measure_temp_threaded():
    global c_buf
    humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, temp_pin)
    temperature = temperature * 9/5.0 + 32
    c_buf.write(temperature)
    time.sleep(3)
    threading.Thread(target=measure_temp_threaded).start()

def measure_temp():
    global c_buf
    print("Measuring temp...")
    humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT22, temp_pin)
    temperature = temperature * 9/5.0 + 32
    print("Read value of %f" % (temperature))
    c_buf.write(temperature)
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
    global c_buf
    global c_state
    global app

    time.sleep(3)

    app.config['SECRET_KEY'] = 'secret'
    app.config['DEBUG'] = True
    socketio = SocketIO(app)

    init_relays()
    measure_temp()
    init_display()

    threading.Thread(target=measure_temp_threaded).start()

    while True:
        temps = c_buf.read_all()
        curr_temp = reduce(lambda x, y: x + y, temps) / float(len(temps))
        socketio.emit('tempHeartbeat', {'temp': curr_temp}, namespace='/data')
        diff = round(curr_temp - ideal_temp, 2)
        print("Current status: %f, %f=>%f\tLast read val: %f at idx %d" % (diff, curr_temp, ideal_temp, c_buf.read(), c_buf.index))
        if diff > 4.0 and (c_state == State.OFF):
            print("Enable cooling: %f, %f=>%f" % (diff, curr_temp, ideal_temp))
            threading.Thread(target=enable_cooling).start()
        if diff < -4.0 and (c_state == State.OFF):
            print("Enable Heating: %f, %f=>%f" % (diff, curr_temp, ideal_temp))
            # enable_heating()
        if c_state == State.COOLING:
            if curr_temp < ideal_temp or abs(diff) < 0.5:
                print("Turning off HVAC: %f, %f=>%f" % (diff, curr_temp, ideal_temp))
                c_state = State.OFF
                threading.Thread(target=disable_cooling).start()
        elif c_state == State.HEATING:
            if curr_temp > ideal_temp or abs(diff) < 0.5:
                print("Turning off HVAC: %f, %f=>%f" % (diff, curr_temp, ideal_temp))
                c_state = State.OFF
                threading.Thread(target=disable_heating).start()

        time.sleep(5)


@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    threading.Thread(target=main).start()
    app.run(host="0.0.0.0", port=5000, debug=True)
