#!/usr/bin/env python
import argparse
import logging
import serial
import serial.threaded
import sys
import time
from enum import Enum


class DeviceIdentifier(Enum):
    ALPHA = 1
    BETA = 2


class ProxyProtocolFactory:
    def __init__(self, dev_id, pass_through=True, data_pass_through_callback=None, data_received_callback=None):
        self.logger = logging.getLogger('ProxyProtocolFactory')
        self.dev_id = dev_id
        self.pass_through = pass_through
        self.data_pass_through_callback = data_pass_through_callback
        self.data_received_callback = data_received_callback
        self.logger.debug(f"__init__: dev_id={self.dev_id}, pass_through={self.pass_through}, data_pass_through_callback={self.data_pass_through_callback}, data_received_callback={self.data_received_callback}")

    def createProxyProtocol(self):
        self.logger.debug(f"createProxyProtocol: creating ProxyProtocol with dev_id={self.dev_id}, pass_through={self.pass_through}, data_pass_through_callback={self.data_pass_through_callback}, data_received_callback={self.data_received_callback}")
        return ProxyProtocol(self.dev_id, self.pass_through, self.data_pass_through_callback, self.data_received_callback)


class ProxyProtocol(serial.threaded.Protocol):
    """
    Read data and write to destination device.
    """
    def __init__(self, dev_id="unknown", pass_through=None, data_pass_through_callback=None, data_received_callback=None):
        self.logger = logging.getLogger('ProxyProtocol')
        self.dev_id = dev_id
        self.pass_through = pass_through
        self.data_pass_through_callback = data_pass_through_callback
        self.data_received_callback = data_received_callback
        self.transport = None
        self.logger.debug(f"__init__: dev_id={self.dev_id}, pass_through={self.pass_through}, data_pass_through_callback={self.data_pass_through_callback}, data_received_callback={self.data_received_callback}")

    def connection_made(self, transport):
        """
        Reader thread is started.
        Parameters:
            transport – instance used to write to serial port.
        """
        self.logger.debug(f"[{self.dev_id.name}] connection_made: port opened")
        # super().connection_made(transport)
        self.transport = transport

    def data_received(self, data):
        """
        Data received from the serial port.
        Parameters:
            data (bytes) - received bytes
        """
        self.logger.debug(f"[{self.dev_id.name}] data_received: len={len(data)}, data={data}")
        # super().data_received(data)
        if self.data_received_callback:
            self.logger.debug(f"[{self.dev_id.name}] calling data received callback")
            data = self.data_received_callback(data)
            self.logger.debug(f"[{self.dev_id.name}] returned from data received callback; len={len(data)}, data={data}")

        if self.pass_through and self.data_pass_through_callback:
            # pass-through data
            self.logger.debug(f"[{self.dev_id.name}] data_received: calling data pass-through callback >>>")
            self.data_pass_through_callback(self.dev_id, data)

    def connection_lost(self, exc):
        """
        Serial port is closed or the reader loop terminated otherwise.
        """
        # super().connection_lost(exc)
        self.transport = None
        self.logger.debug(f"[{self.dev_id.name}] connection_lost: port closed")
        if exc:
            self.logger.debug(f"[{self.dev_id.name}] connection_lost: exception={exc}")
            self.logger.exception(f"[{self.dev_id.name}] connection_lost: exception")


class SerialProcessor:
    def __init__(self, conf_a, conf_b):
        super().__init__()
        self.logger = logging.getLogger('SerialProcessor')
        self.thread_a = None
        self.transport_a = None
        self.protocol_a = None
        self.thread_b = None
        self.transport_b = None
        self.protocol_b = None
        self.conf_a = conf_a
        self.conf_b = conf_b

        self.ser_a = serial.Serial(
            port=self.conf_a['device'],
            baudrate=self.conf_a['baudrate'],
            parity=self.conf_a['parity'],
            stopbits=self.conf_a['stopbits'],
            bytesize=self.conf_a['bytesize'],
            timeout=self.conf_a['timeout'],
        )

        self.ser_b = serial.Serial(
            port=self.conf_b['device'],
            baudrate=self.conf_b['baudrate'],
            parity=self.conf_b['parity'],
            stopbits=self.conf_b['stopbits'],
            bytesize=self.conf_b['bytesize'],
            timeout=self.conf_b['timeout'],
        )

        self.ser_a.flushInput()
        self.ser_b.flushInput()
        self.logger.debug(f"__init__: conf_a={self.conf_a}, conf_b={self.conf_b}")
        logging.info(f"{DeviceIdentifier.ALPHA.name} device: {self.conf_a['device']}")
        logging.info(f"{DeviceIdentifier.BETA.name} device: {self.conf_b['device']}")

    def start(self):
        """Start the reader threads."""
        self.logger.info(f"starting reader threads")

        self.thread_a = serial.threaded.ReaderThread(self.ser_a, ProxyProtocolFactory(DeviceIdentifier.ALPHA, pass_through=self.conf_a['pass_through'], data_pass_through_callback=self.data_pass_through, data_received_callback=self.conf_a['data_received_callback']).createProxyProtocol)
        # Note: Start the thread’s activity. It arranges for the object’s run() method to be invoked in a separate thread of control.
        self.thread_a.start()
        self.transport_a, self.protocol_a = self.thread_a.connect()
        self.logger.debug(f"start: thread_a={self.thread_a}, transport_a={self.transport_a}, protocol_a={self.protocol_a}")

        self.thread_b = serial.threaded.ReaderThread(self.ser_b, ProxyProtocolFactory(DeviceIdentifier.BETA, pass_through=self.conf_b['pass_through'], data_pass_through_callback=self.data_pass_through, data_received_callback=self.conf_b['data_received_callback']).createProxyProtocol)
        self.thread_b.start()
        self.transport_b, self.protocol_b = self.thread_b.connect()
        self.logger.debug(f"start: thread_b={self.thread_b}, transport_b={self.transport_b}, protocol_b={self.protocol_b}")

    def stop(self):
        """Stop the reader threads."""
        self.logger.info(f"stop: closing reader threads")
        self.thread_a.close()
        self.thread_b.close()

    def write(self, device_id, data):
        """Write data to the device identified by device_id."""
        self.logger.info(f"write: device_id={device_id}, data={data}")
        if device_id == DeviceIdentifier.ALPHA:
            self.thread_a.write(data)
        elif device_id == DeviceIdentifier.BETA:
            self.thread_b.write(data)
        else:
            self.logger.error(f"write: unknown device identifier '{device_id}'")

    def data_pass_through(self, device_id, data):
        self.logger.debug(f"data_pass_through: device_id={device_id}, data={data}")
        if device_id == DeviceIdentifier.ALPHA:
            self.thread_b.write(data)
        elif device_id == DeviceIdentifier.BETA:
            self.thread_a.write(data)
        else:
            self.logger.error(f"data_pass_through: unknown device identifier '{device_id}'")
            return False
        return True

    def set_pass_through(self, device_id, value):
        self.logger.debug(f"set_pass_through: device_id={device_id}, value={value}")
        if device_id == DeviceIdentifier.ALPHA:
            self.protocol_a.pass_through = value
        elif device_id == DeviceIdentifier.BETA:
            self.protocol_b.pass_through = value
        else:
            self.logger.error(f"set_pass_through: unknown device identifier '{device_id}'")
            return False
        return True


# Simple test client
def main(argv):
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("alphadev", help="alpha serial device")
        parser.add_argument("betadev", help="beta serial device")
        parser.add_argument("-l", "--log", default=None, help="output log filename")
        args = parser.parse_args()

        logging.basicConfig(level=logging.DEBUG, filename=args.log)

        conf_a = {
            'device': args.alphadev,
            'baudrate': 115200,
            'parity': serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE,
            'bytesize': serial.EIGHTBITS,
            'timeout': 1,
            'pass_through': True,
            'data_received_callback': reverse_data_received
        }
        conf_b = {
            'device': args.betadev,
            'baudrate': 115200,
            'parity': serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE,
            'bytesize': serial.EIGHTBITS,
            'timeout': 1,
            'pass_through': True,
            'data_received_callback': None
        }

        processor = SerialProcessor(conf_a, conf_b)
        processor.start()

        input("\n\nData proxy pass-through started; Press Enter to exit...\n")

        # prime processor with data for testing
        # processor.write(DeviceIdentifier.ALPHA, 'helloA\r\n'.encode())
        # time.sleep(2)
        # processor.write(DeviceIdentifier.BETA, 'helloB\r\n'.encode())
        # time.sleep(2)
    finally:
        processor.stop()
        logging.shutdown()

def print_data_received(data):
        logging.info(f"(print_data_received: len={len(data)}, data={data}")
        return data

def reverse_data_received(data):
        logging.info(f"reverse_data_received: len={len(data)}, data={data}")
        tmp = bytearray(data)
        tmp.reverse()
        logging.debug(f"reverse_data_received: tmp={tmp}")
        return tmp


if __name__ == "__main__":
    main(sys.argv)
