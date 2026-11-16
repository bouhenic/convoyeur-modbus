#!/usr/bin/env python3
"""Tests du robot Ned2 virtuel : table Modbus Niryo, float32, mouvements, prise."""
import math
import threading
import time
import unittest

from modbus_core import ModbusError, ModbusTcpClient, machine, start_server
from robot_ned2 import (HOME, POSES, forward, inverse, robot, process_pdu_robot,
                        describe_robot, floats_to_regs, regs_to_floats)


class Horloge(threading.Thread):
    """Fait avancer la simulation, comme le ferait l'interface graphique."""
    def __init__(self):
        super().__init__(daemon=True)
        self.stop = threading.Event()

    def run(self):
        last = time.monotonic()
        while not self.stop.wait(0.01):
            now = time.monotonic()
            # Simulation accélérée ×5 pour des tests rapides.
            machine.advance((now - last) * 5)
            robot.advance((now - last) * 5)
            last = now


class TestCinematique(unittest.TestCase):
    def test_pose_zero_et_home(self):
        x, y, z, r, p, w = forward([0.0] * 6)
        self.assertAlmostEqual(x, 0.2952, places=3)
        self.assertAlmostEqual(z, 0.429, places=3)
        self.assertAlmostEqual(p, 0.0, places=3)
        self.assertAlmostEqual(forward(HOME)[4], 0.75, places=2)

    def test_inverse(self):
        for name, pose in POSES.items():
            with self.subTest(pose=name):
                q = inverse(pose, HOME)
                self.assertIsNotNone(q)
                for a, b in zip(forward(q)[:3], pose[:3]):
                    self.assertAlmostEqual(a, b, places=3)
        self.assertIsNone(inverse([0.8, 0, 0.1, 0, math.pi / 2, 0], HOME))


class TestModbusNed2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = start_server('127.0.0.1', 0, process=process_pdu_robot,
                                  describe=describe_robot, accept_unit=lambda u: True,
                                  idle_timeout=None, clients=set())
        cls.port = cls.server.server_address[1]
        robot.conveyor = machine

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        robot.reset()
        machine.__init__()
        self.clock = Horloge()
        self.clock.start()
        self.client = ModbusTcpClient('127.0.0.1', self.port, timeout=30)
        self.client.connect()

    def tearDown(self):
        self.client.close()
        self.clock.stop.set()

    def floats(self, fc, addr, n):
        return regs_to_floats(self.client.read(fc, addr, 2 * n)[0])

    def move_joints(self, joints):
        self.client.write_registers(50, floats_to_regs(joints))
        self.client.write_register(74, 0)
        self.client.write_coil(113, True)

    def test_adresses_et_etat_initial(self):
        self.assertEqual(self.client.read(4, 120, 2)[0], [0, 11])    # résultat, outil
        joints = self.floats(4, 50, 6)
        for a, b in zip(joints, HOME):
            self.assertAlmostEqual(a, b, places=5)
        pose = self.floats(4, 62, 6)
        self.assertAlmostEqual(pose[0], forward(HOME)[0], places=4)
        self.assertEqual(self.client.read(1, 113, 6)[0], [0, 0, 0, 0, 0, 1])
        self.assertEqual(self.client.read(2, 50, 3)[0], [1, 0, 0])
        self.assertEqual(self.client.read(3, 142, 1)[0], [100])

    def test_adresse_non_attribuee(self):
        for fc, addr in [(1, 4), (1, 53), (3, 87), (4, 100), (2, 5)]:
            with self.subTest(fc=fc, addr=addr):
                with self.assertRaises(ModbusError) as exc:
                    self.client.read(fc, addr, 1)
                self.assertEqual(exc.exception.code, 2)

    def test_mouvement_bloquant(self):
        target = [0.3, 0.0, -0.4, 0.0, -0.6, 0.2]
        t0 = time.monotonic()
        self.move_joints(target)          # bloque jusqu'à la fin du mouvement
        self.assertGreater(time.monotonic() - t0, 0.1)
        self.assertEqual(self.client.read(1, 113, 1)[0], [0])
        for a, b in zip(self.floats(4, 50, 6), target):
            self.assertAlmostEqual(a, b, places=4)
        self.assertEqual(self.client.read(4, 120, 1)[0], [0])

    def test_mouvement_non_bloquant_et_pose(self):
        self.client.write_coil(118, False)
        self.client.write_registers(62, floats_to_regs(POSES['prise']))
        self.client.write_register(74, 1)
        self.client.write_coil(113, True)
        self.assertEqual(self.client.read(1, 113, 1)[0], [1])    # encore en mouvement
        while self.client.read(1, 113, 1)[0] == [1]:
            time.sleep(0.02)
        for a, b in zip(self.floats(4, 62, 3), POSES['prise'][:3]):
            self.assertAlmostEqual(a, b, places=3)

    def test_erreur_dans_ir120_sans_exception_modbus(self):
        self.client.write_registers(62, floats_to_regs([0.9, 0, 0.1, 0, 1.57, 0]))
        self.client.write_register(74, 1)
        self.client.write_coil(113, True)          # pas d'exception Modbus…
        self.assertEqual(self.client.read(4, 120, 1)[0], [2])   # …mais résultat 2
        self.move_joints([0.0, 0.0, 3.0, 0.0, 0.0, 0.0])        # hors limites J3
        self.assertEqual(self.client.read(4, 120, 1)[0], [2])

    def test_fc06_sur_un_float_est_ignore(self):
        self.client.write_registers(50, floats_to_regs([0.5]))
        self.client.write_register(50, 0x3F80)     # moitié d'un float : ignoré
        self.assertAlmostEqual(self.floats(3, 50, 1)[0], 0.5, places=6)
        self.client.write_register(400, 7)         # entier : accepté
        self.assertEqual(self.client.read(3, 400, 1)[0], [7])

    def test_fc15_et_zone_utilisateur(self):
        self.client.write_coils(200, [True, False, True])
        self.assertEqual(self.client.read(1, 200, 3)[0], [1, 0, 1])
        self.client.write_registers(200, floats_to_regs([3.25]))
        self.assertAlmostEqual(self.floats(3, 200, 1)[0], 3.25)

    def test_collision(self):
        robot.collision = True
        self.move_joints([0.2, 0, 0, 0, 0, 0])
        self.assertEqual(self.client.read(4, 120, 1)[0], [2])
        self.client.write_coil(117, False)
        self.move_joints([0.2, 0, 0, 0, 0, 0])
        self.assertEqual(self.client.read(4, 120, 1)[0], [0])

    def test_prise_et_depose(self):
        machine.set_robot_cell(True)
        machine.set_run(True)
        while self.client.read(2, 0, 1)[0] != [1]:    # DI1 = carton en bout
            time.sleep(0.02)
        machine.set_run(False)
        self.client.write_coil(51, False)
        for name, kind in [('au-dessus prise', 1), ('prise', 2)]:
            self.client.write_registers(62, floats_to_regs(POSES[name]))
            self.client.write_register(74, kind)
            self.client.write_coil(113, True)
        self.client.write_coil(51, True)
        self.assertTrue(robot.held)
        self.assertEqual(machine.count, 1)
        for name, kind in [('au-dessus prise', 2), ('bac B', 1)]:
            self.client.write_registers(62, floats_to_regs(POSES[name]))
            self.client.write_register(74, kind)
            self.client.write_coil(113, True)
        self.client.write_coil(51, False)
        self.assertEqual(robot.bins['B'], 1)

    def test_programme_embarque(self):
        machine.set_robot_cell(True)
        robot.start_program()
        machine.set_run(True)
        end = time.monotonic() + 20
        while robot.bins['A'] < 2 and time.monotonic() < end:
            time.sleep(0.05)
        robot.stop_program()
        self.assertGreaterEqual(robot.bins['A'], 2)
        self.assertGreaterEqual(self.client.read(3, 401, 1)[0][0], 2)

    def test_accumulation_bourrage(self):
        machine.set_robot_cell(True)
        machine.set_run(True)
        end = time.monotonic() + 20
        while machine.fault_code == 0 and time.monotonic() < end:
            time.sleep(0.05)
        self.assertEqual(machine.fault_code, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
