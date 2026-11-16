#!/usr/bin/env python3
"""Tests d'intégration : sans ESP32, sans écran, sans dépendance externe."""
import socket
import struct
import threading
import time
import unittest

from modbus_core import (Machine, ModbusError, ModbusTcpClient,
                         process_pdu, start_server, machine)


class TestProtocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server('127.0.0.1', 0)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        with machine.lock:
            machine.command_run = False
            machine.speed = 50
            machine.target = 0
            machine.count = 0
            machine.boxes = []
            machine.jam_present = False
            machine.estop_pressed = False
            machine.fault_code = 0
            machine.simtime = 0
            machine.entry_until = 0
            machine.exit_until = 0
        self.client = ModbusTcpClient('127.0.0.1', self.port)
        self.client.connect()

    def tearDown(self):
        self.client.close()

    def test_read_base(self):
        value, req, resp = self.client.read(4, 0, 7)
        self.assertEqual(value, [0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(req[7:], bytes.fromhex('04 00 00 00 07'))
        self.assertEqual(resp[7:], bytes.fromhex('04 0E') + b'\x00' * 14)
        self.assertEqual(self.client.read(3, 0, 2)[0], [50, 0])
        self.assertEqual(self.client.read(1, 0, 3)[0], [0, 0, 0])
        self.assertEqual(self.client.read(2, 0, 2)[0], [0, 0])

    def test_start_speed_target(self):
        self.client.write_register(0, 75)
        self.client.write_register(1, 2)
        self.assertEqual(self.client.read(3, 0, 2)[0], [75, 2])
        self.client.write_coil(0, True)
        self.assertEqual(self.client.read(1, 0, 1)[0], [1])
        self.assertEqual(self.client.read(4, 1, 1)[0], [1])
        for _ in range(450):
            machine.advance(0.04)
        self.assertGreaterEqual(self.client.read(4, 0, 1)[0][0], 2)
        self.assertEqual(self.client.read(4, 6, 1)[0], [3])
        self.assertEqual(self.client.read(4, 1, 1)[0], [0])
        with self.assertRaises(ModbusError) as exc:
            self.client.write_coil(0, True)
        self.assertEqual(exc.exception.code, 4)
        self.client.write_coil(2, True)
        self.assertEqual(self.client.read(4, 0, 1)[0], [0])
        self.client.write_coil(0, True)
        self.assertEqual(self.client.read(4, 1, 1)[0], [1])
        self.client.write_coil(0, False)
        self.assertEqual(self.client.read(4, 1, 1)[0], [0])

    def test_jam_and_acknowledge(self):
        self.client.write_coil(0, True)
        machine.inject_jam()
        self.assertEqual(self.client.read(4, 4, 1)[0], [1])
        self.assertEqual(self.client.read(2, 0, 1)[0], [1])
        with self.assertRaises(ModbusError):
            self.client.write_coil(1, True)
        machine.release_jam()
        self.client.write_coil(1, True)
        self.assertEqual(self.client.read(4, 4, 1)[0], [0])
        self.client.write_coil(0, True)
        machine.press_estop()
        self.assertEqual(self.client.read(4, 4, 1)[0], [2])
        machine.release_estop()
        self.client.write_coil(1, True)
        self.assertEqual(self.client.read(4, 4, 1)[0], [0])

    def test_exceptions(self):
        cases = [
            (4, 99, 1, 2),  # Adresse hors table
            (4, 0, 0, 3),   # Quantité nulle
            (6, 0, 0, 3),   # Vitesse invalide
            (6, 1, 6000, 3),
            (5, 0, 100, 3),
            (5, 10, 0xFF00, 2),
            (0x63, 0, 1, 1),
        ]
        for fc, address, val, error in cases:
            with self.subTest(fc=fc, addr=address, val=val):
                with self.assertRaises(ModbusError) as exc:
                    self.client.exchange(fc, address, val)
                self.assertEqual(exc.exception.code, error)

    def test_raw_pdu(self):
        self.client.write_coil(0, True)
        pdu, request, response = self.client.exchange_raw(bytes.fromhex('04 00 01 00 01'))
        self.assertEqual(pdu, bytes.fromhex('04 02 00 01'))
        self.assertEqual(request[7:], bytes.fromhex('04 00 01 00 01'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
