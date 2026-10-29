#!/usr/bin/env python3

# *****************************************
# PiFire Prototype Interface Library (Patched for RPi.GPIO)
# *****************************************

import time
import RPi.GPIO as GPIO
from gpiozero.threads import GPIOThread
from common import is_float, create_logger, get_os_info

class GrillPlatform:
    def __init__(self, config):
        self.logger = create_logger('control')
        try:
            self.out_pins = config.get('outputs', {})
            self.in_pins = config.get('inputs', {})
            self.dc_fan = config.get('dc_fan', False)
            self.frequency = config.get('frequency', 100)
            self.standalone = config.get('standalone', True)
            self.trigger_level = config.get('triggerlevel', 'HIGH')
            self.current = {}
        except Exception as e:
            self.logger.error(f'Error parsing platform configuration: {e}')

        # Setup RPi.GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # Determine active states based on trigger level
        if self.trigger_level == 'LOW':
            self.ACTIVE = GPIO.LOW
            self.INACTIVE = GPIO.HIGH
        else:
            self.ACTIVE = GPIO.HIGH
            self.INACTIVE = GPIO.LOW

        # Setup output pins
        for key, pin in self.out_pins.items():
            if isinstance(pin, int) and pin >= 0:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, self.INACTIVE)

        if self.dc_fan:
            self._ramp_thread = None
            self.out_pins['pwm'] = 100

        self.state_auger = False
        self.state_fan = False
        self.state_igniter = False
        self.state_power = False

    def _set_pin(self, pin_name, state):
        pin = self.out_pins.get(pin_name)
        if isinstance(pin, int) and pin >= 0:
            val = self.ACTIVE if state else self.INACTIVE
            GPIO.output(pin, val)
            self.logger.debug(f"Prototype Platform: Setting {pin_name} (Pin {pin}) to {'ON' if state else 'OFF'}")

    def auger_on(self):
        self.state_auger = True
        self._set_pin('auger', True)

    def auger_off(self):
        self.state_auger = False
        self._set_pin('auger', False)

    def fan_on(self, duty_cycle=100):
        self.state_fan = True
        self._set_pin('fan', True)
        if self.dc_fan:
            self._stop_ramp()
            self.set_duty_cycle(duty_cycle)

    def fan_off(self):
        self.state_fan = False
        self._set_pin('fan', False)

    def fan_toggle(self):
        if self.state_fan:
            self.fan_off()
        else:
            self.fan_on()

    def set_duty_cycle(self, percent):
        self._stop_ramp()
        duty_cycle = float((100 - percent) / 100.0)
        self.out_pins['pwm'] = duty_cycle

    def pwm_fan_ramp(self, on_time=5, min_duty_cycle=20, max_duty_cycle=100):
        self.fan_on()
        self._start_ramp(on_time=on_time, min_duty_cycle=min_duty_cycle, max_duty_cycle=max_duty_cycle)

    def set_pwm_frequency(self, frequency=100):
        self.frequency = frequency

    def igniter_on(self):
        self.state_igniter = True
        self._set_pin('igniter', True)

    def igniter_off(self):
        self.state_igniter = False
        self._set_pin('igniter', False)

    def power_on(self):
        self.state_power = True
        self._set_pin('power', True)

    def power_off(self):
        self.state_power = False
        self._set_pin('power', False)

    def get_input_status(self):
        return self.in_pins.get('selector', False)

    def set_input_status(self, value):
        self.in_pins['selector'] = value

    def get_output_status(self):
        self.current = {
            'auger': self.state_auger,
            'igniter': self.state_igniter,
            'power': self.state_power,
            'fan': self.state_fan
        }
        if self.dc_fan:
            self.current['pwm'] = 100 - (self.out_pins.get('pwm', 1.0) * 100)
            self.current['frequency'] = self.frequency
        return self.current

    def _start_ramp(self, on_time, min_duty_cycle, max_duty_cycle, background=True):
        self._stop_ramp()
        self._ramp_thread = GPIOThread(self._ramp_device, (on_time, min_duty_cycle, max_duty_cycle))
        self._ramp_thread.start()
        if not background:
            self._ramp_thread.join()
            self._ramp_thread = None

    def _stop_ramp(self):
        if self._ramp_thread:
            self._ramp_thread.stop()
            self._ramp_thread = None

    def _ramp_device(self, on_time, min_duty_cycle, max_duty_cycle, fps=25):
        duty_cycle = max_duty_cycle / 100
        sequence = []
        sequence += [
            (1 - (i * (duty_cycle / fps) / on_time), 1 / fps)
            for i in range(int((fps * on_time) * (min_duty_cycle / max_duty_cycle)), int(fps * on_time))
        ]
        sequence.append((1.0 - duty_cycle, 1 / fps))
        for value, delay in sequence:
            percent = round(float(100 - (value * 100)), 4)
            self.out_pins['pwm'] = percent
            if self._ramp_thread.stopping.wait(delay):
                break

    def cleanup(self):
        self.power_off()
        self.igniter_off()
        self.auger_off()
        self.fan_off()
        GPIO.cleanup()

    def supported_commands(self, arglist):
        return {
            'result': 'OK',
            'message': 'Supported commands listed.',
            'data': {'supported_cmds': ['check_throttled', 'check_wifi_quality', 'check_cpu_temp', 'check_alive', 'scan_bluetooth', 'os_info', 'network_info', 'hardware_info']}
        }

    def check_throttled(self, arglist):
        return {'result': 'OK', 'message': 'No throttling.', 'data': {'cpu_under_voltage': False, 'cpu_throttled': False}}

    def check_wifi_quality(self, arglist):
        return {'result': 'OK', 'message': 'Success.', 'data': {'wifi_quality_value': 60, 'wifi_quality_max': 70, 'wifi_quality_percentage': 80}}

    def check_cpu_temp(self, arglist):
        return {'result': 'OK', 'message': 'Success.', 'data': {'cpu_temp': 40.0}}

    def check_alive(self, arglist):
        return {'result': 'OK', 'message': 'Running.', 'data': {}}

    def scan_bluetooth(self, arglist):
        return {'result': 'OK', 'message': 'Scanned.', 'data': {'bt_devices': []}}

    def os_info(self, arglist):
        return {'result': 'OK', 'message': 'Retrieved.', 'data': get_os_info()}

    def network_info(self, arglist):
        return {'result': 'OK', 'message': 'Retrieved.', 'data': {}}

    def hardware_info(self, arglist):
        return {'result': 'OK', 'message': 'Retrieved.', 'data': {'cpu_info': {}, 'total_ram': 0, 'available_ram': 0}}
