"""Moteur de simulation et serveur Modbus TCP minimal — usage pédagogique.
Bibliothèque standard uniquement. Adresses Modbus exprimées en offsets à partir de 0.
"""
from collections import deque
from dataclasses import dataclass
import socket
import socketserver
import struct
import threading
import time

PORT = 1502
UNIT_ID = 1


def hx(data):
    return data.hex(' ').upper()


def local_ipv4():
    """IP de ce PC sur le réseau local (celle à donner aux pupitres distants)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('192.0.2.1', 1))  # UDP : aucun paquet n'est envoyé.
        address = s.getsockname()[0]
        s.close()
        return address
    except OSError:
        return 'IP du PC'


@dataclass
class Event:
    stamp: str
    peer: str
    action: str
    request: str
    response: str
    explanation: str


class Machine:
    END = 1.0           # position d'arrêt en bout de tapis (poste robot)
    SPACING = .085      # écart entre deux cartons accumulés
    QUEUE_JAM = 4       # cartons accumulés provoquant un bourrage
    ROBOT_PERIOD = 5.0  # intervalle entre deux cartons en mode poste robot (s)

    def __init__(self):
        self.lock = threading.RLock()
        self.command_run = False
        self.speed = 50
        self.target = 0
        self.count = 0
        self.boxes = []
        self.spawn_elapsed = 1.0
        self.entry_until = 0.0
        self.exit_until = 0.0
        self.fault_code = 0
        self.jam_present = False
        self.estop_pressed = False
        self.simtime = 0.0
        self.events = deque(maxlen=600)
        self.event_id = 0
        self.clients = set()
        # Poste robot : les cartons s'arrêtent en bout de tapis et attendent
        # d'être saisis ; sinon ils quittent le tapis et sont comptés.
        self.robot_cell = False

    def is_goal(self):
        return self.target > 0 and self.count >= self.target

    def is_running(self):
        return self.command_run and self.fault_code == 0 and not self.is_goal()

    def status(self):
        if self.fault_code:
            return 2
        if self.is_goal():
            return 3
        return 1 if self.is_running() else 0

    def set_run(self, on):
        with self.lock:
            if on and (self.fault_code or self.is_goal()):
                return False
            self.command_run = bool(on)
            return True

    def set_speed(self, speed):
        with self.lock:
            if not 1 <= int(speed) <= 100:
                return False
            self.speed = int(speed)
            return True

    def set_target(self, target):
        with self.lock:
            if not 0 <= int(target) <= 5000:
                return False
            self.target = int(target)
            if self.is_goal():
                self.command_run = False
            return True

    def inject_jam(self):
        with self.lock:
            self.jam_present = True
            self.fault_code = 1
            self.command_run = False

    def release_jam(self):
        with self.lock:
            self.jam_present = False
            if self.robot_cell and self.boxes:
                # Dégager la file d'attente : seul le carton de tête reste.
                self.boxes = [max(self.boxes)]

    def press_estop(self):
        with self.lock:
            self.estop_pressed = True
            self.fault_code = 2
            self.command_run = False

    def release_estop(self):
        with self.lock:
            self.estop_pressed = False

    def acknowledge(self):
        with self.lock:
            if self.jam_present or self.estop_pressed:
                return False
            self.fault_code = 0
            return True

    def set_robot_cell(self, on):
        with self.lock:
            self.robot_cell = bool(on)

    def box_at_end(self):
        with self.lock:
            return self.robot_cell and any(p >= self.END - 1e-6 for p in self.boxes)

    def box_positions(self):
        with self.lock:
            return list(enumerate(self.boxes))

    def take_box(self, index):
        """Le robot retire un carton du tapis : il compte comme produit."""
        with self.lock:
            if 0 <= index < len(self.boxes):
                self.boxes.pop(index)
                self.count += 1
                self.exit_until = self.simtime + .45
                if self.is_goal():
                    self.command_run = False

    def reset_count(self):
        with self.lock:
            self.count = 0
            self.command_run = False
            self.boxes.clear()
            self.spawn_elapsed = 1.0
            self.entry_until = self.exit_until = 0

    def coils(self):
        return [int(self.command_run), 0, 0]

    def discretes(self):
        return [int(self.fault_code != 0), int(self.is_goal())]

    def holding(self):
        return [self.speed, self.target]

    def exit_sensor(self):
        if self.robot_cell:
            return any(p >= self.END - 1e-6 for p in self.boxes)
        return self.simtime < self.exit_until

    def inputs(self):
        return [self.count & 0xFFFF, int(self.is_running()),
                int(self.simtime < self.entry_until),
                int(self.exit_sensor()),
                self.fault_code, len(self.boxes), self.status()]

    def snapshot(self):
        with self.lock:
            return dict(running=self.is_running(), command_run=self.command_run,
                        speed=self.speed, target=self.target, count=self.count,
                        boxes=tuple(self.boxes), inputs=self.inputs(),
                        coils=self.coils(), discretes=self.discretes(),
                        holding=self.holding(), jam_present=self.jam_present,
                        estop_pressed=self.estop_pressed, clients=len(self.clients),
                        robot_cell=self.robot_cell)

    def advance(self, delta):
        delta = max(0, min(delta, .20))
        with self.lock:
            self.simtime += delta
            if not self.is_running():
                return
            self.spawn_elapsed += delta
            # Poste robot : cadence adaptée au cycle de prise (≈ 4,5 s à 100 %).
            period = self.ROBOT_PERIOD if self.robot_cell else 1.35
            if self.spawn_elapsed >= period:
                self.spawn_elapsed -= period
                self.boxes.append(0.0)
                self.entry_until = self.simtime + .30
            velocity = .075 + .0032 * self.speed
            if self.robot_cell:
                # Accumulation : chaque carton s'arrête derrière le précédent.
                limit, moved = self.END, []
                for pos in sorted(self.boxes, reverse=True):
                    new = min(pos + velocity * delta, limit)
                    moved.append(new)
                    limit = new - self.SPACING
                self.boxes = moved
                n = self.QUEUE_JAM
                if len(moved) >= n and moved[n - 1] >= self.END - (n - 1) * self.SPACING - 1e-6:
                    self.jam_present = True
                    self.fault_code = 1
                    self.command_run = False
                return
            self.boxes = [x + velocity * delta for x in self.boxes]
            finished = sum(pos >= 1 for pos in self.boxes)
            if finished:
                self.count += finished
                self.exit_until = self.simtime + .45
            self.boxes = [pos for pos in self.boxes if pos < 1]
            if self.is_goal():
                self.command_run = False

    def add_log(self, peer, action, request, response, explanation):
        with self.lock:
            self.event_id += 1
            event = Event(time.strftime('%H:%M:%S'), peer, action,
                          hx(request), hx(response), explanation)
            self.events.append((self.event_id, event))
            return event

    def logs_after(self, event_id):
        with self.lock:
            return [(i, e) for i, e in self.events if i > event_id]


machine = Machine()


def error(fc, code):
    return bytes([fc | 0x80, code])


def decode(pdu):
    if len(pdu) < 1:
        return 'Trame vide'
    fc = pdu[0]
    if fc in (15, 16) and len(pdu) >= 6:
        addr, qty = struct.unpack('>HH', pdu[1:5])
        kind = 'coils' if fc == 15 else 'registres'
        return f'Écrire {qty} {kind} à partir de l’offset {addr}'
    if len(pdu) != 5:
        return f'FC{fc:02X} / longueur incorrecte'
    addr, value = struct.unpack('>HH', pdu[1:])
    terms = {1: 'Lire coils', 2: 'Lire entrées TOR', 3: 'Lire Holding Registers',
             4: 'Lire Input Registers', 5: 'Écrire coil', 6: 'Écrire registre'}
    if fc in (1, 2, 3, 4):
        return f'{terms[fc]} · offset {addr} · quantité {value}'
    if fc == 5:
        return f'Écrire coil {addr} = {"1" if value == 0xFF00 else "0" if value == 0 else hex(value)}'
    if fc == 6:
        return f'Écrire registre {addr} = {value}'
    return f'Fonction {fc} non prise en charge'


def process_pdu(pdu):
    if not pdu:
        return b''
    fc = pdu[0]
    if fc not in (1, 2, 3, 4, 5, 6):
        return error(fc, 1)
    if len(pdu) != 5:
        return error(fc, 3)
    addr, value = struct.unpack('>HH', pdu[1:])
    with machine.lock:
        if fc in (1, 2, 3, 4):
            table = {1: machine.coils, 2: machine.discretes,
                     3: machine.holding, 4: machine.inputs}[fc]()
            # Les limites standards sont respectées même si notre table est petite.
            max_qty = 2000 if fc in (1, 2) else 125
            if value < 1 or value > max_qty:
                return error(fc, 3)
            if addr + value > len(table):
                return error(fc, 2)
            values = table[addr:addr + value]
            if fc in (1, 2):
                packed = bytearray((len(values) + 7) // 8)
                for i, bit in enumerate(values):
                    if bit:
                        packed[i // 8] |= 1 << (i % 8)
                return bytes((fc, len(packed))) + bytes(packed)
            return bytes((fc, len(values) * 2)) + b''.join(
                struct.pack('>H', v) for v in values)
        if fc == 5:
            if addr > 2:
                return error(fc, 2)
            if value not in (0x0000, 0xFF00):
                return error(fc, 3)
            if value == 0xFF00:
                if addr == 0 and not machine.set_run(True):
                    return error(fc, 4)
                if addr == 1 and not machine.acknowledge():
                    return error(fc, 4)
                if addr == 2:
                    machine.reset_count()
            elif addr == 0:
                machine.set_run(False)
            return pdu
        if fc == 6:
            if addr > 1:
                return error(fc, 2)
            ok = machine.set_speed(value) if addr == 0 else machine.set_target(value)
            return pdu if ok else error(fc, 3)
    return error(fc, 1)


def recv_exact(sock, n):
    chunks = bytearray()
    while len(chunks) < n:
        piece = sock.recv(n - len(chunks))
        if not piece:
            return None
        chunks.extend(piece)
    return bytes(chunks)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        srv = self.server
        addr = self.client_address[0]
        with srv.clients_lock:
            srv.clients.add((addr, self.client_address[1]))
        self.request.settimeout(srv.idle_timeout)
        try:
            while True:
                header = recv_exact(self.request, 7)
                if header is None:
                    break
                txid, protocol, length, unit = struct.unpack('>HHHB', header)
                if protocol != 0 or not (2 <= length <= 254):
                    break
                pdu = recv_exact(self.request, length - 1)
                if pdu is None:
                    break
                response_pdu = srv.process(pdu) if srv.accept_unit(unit) else None
                if response_pdu is None:
                    # Autre Unit ID : ignorer (permet d'illustrer un timeout).
                    continue
                if not response_pdu:
                    break
                response = struct.pack('>HHHB', txid, 0, len(response_pdu) + 1, unit) + response_pdu
                self.request.sendall(response)
                remark = srv.describe(pdu)
                if response_pdu[0] & 0x80:
                    remark += f' → exception Modbus {response_pdu[1]:02X}'
                machine.add_log(f'{addr} → :{srv.server_address[1]}', f'FC{pdu[0]:02d}',
                                header + pdu, response, remark)
        except (OSError, TimeoutError, ValueError, struct.error):
            pass
        finally:
            with srv.clients_lock:
                srv.clients.discard((addr, self.client_address[1]))


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_server(host='127.0.0.1', port=PORT, process=None, describe=None,
                 accept_unit=None, idle_timeout=12, clients=None):
    """Serveur Modbus TCP générique. Par défaut : le convoyeur (Unit ID 1)."""
    server = Server((host, port), Handler)
    server.process = process or process_pdu
    server.describe = describe or decode
    server.accept_unit = accept_unit or (lambda unit: unit == UNIT_ID)
    server.idle_timeout = idle_timeout
    server.clients = machine.clients if clients is None else clients
    server.clients_lock = machine.lock if clients is None else threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class ModbusTcpClient:
    """Client très simple pour observer les octets, sans PyModbus."""
    def __init__(self, host='127.0.0.1', port=PORT, unit=UNIT_ID, timeout=2):
        self.host, self.port, self.unit = host, port, unit
        self.timeout = timeout
        self.sock = None
        self.txid = 0

    def connect(self):
        self.close()
        self.sock = socket.create_connection((self.host, self.port), timeout=1.5)
        self.sock.settimeout(self.timeout)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def exchange(self, fc, address, value):
        return self.exchange_raw(struct.pack('>BHH', fc, address, value))

    def exchange_raw(self, pdu):
        if self.sock is None:
            self.connect()
        self.txid = (self.txid + 1) & 0xFFFF
        request = struct.pack('>HHHB', self.txid, 0, len(pdu) + 1, self.unit) + pdu
        try:
            self.sock.sendall(request)
            header = recv_exact(self.sock, 7)
            if not header:
                raise ConnectionError('Connexion interrompue')
            txid, proto, length, unit = struct.unpack('>HHHB', header)
            if (txid, proto, unit) != (self.txid, 0, self.unit) or not (2 <= length <= 254):
                raise ValueError('En-tête MBAP incorrect')
            response_pdu = recv_exact(self.sock, length - 1)
            if response_pdu is None:
                raise ConnectionError('Réponse incomplète')
            response = header + response_pdu
            if response_pdu[0] & 0x80:
                raise ModbusError(response_pdu[1], request, response)
            return response_pdu, request, response
        except (OSError, ConnectionError, ValueError):
            self.close()
            raise

    def read(self, fc, address, quantity):
        pdu, req, resp = self.exchange(fc, address, quantity)
        if len(pdu) < 2 or pdu[0] != fc or len(pdu[2:]) != pdu[1]:
            raise ValueError('Réponse de lecture incohérente')
        if fc in (1, 2):
            values = [(pdu[2 + i // 8] >> (i % 8)) & 1 for i in range(quantity)]
        else:
            if pdu[1] != quantity * 2:
                raise ValueError('Taille des registres invalide')
            values = list(struct.unpack('>' + 'H' * quantity, pdu[2:]))
        return values, req, resp

    def write_coil(self, addr, state):
        return self.exchange(5, addr, 0xFF00 if state else 0x0000)

    def write_register(self, addr, value):
        return self.exchange(6, addr, value)

    def write_registers(self, addr, values):
        """FC16 : écrire plusieurs registres consécutifs."""
        data = b''.join(struct.pack('>H', v & 0xFFFF) for v in values)
        return self.exchange_raw(struct.pack('>BHHB', 16, addr, len(values), len(data)) + data)

    def write_coils(self, addr, states):
        """FC15 : écrire plusieurs coils consécutives."""
        packed = bytearray((len(states) + 7) // 8)
        for i, state in enumerate(states):
            if state:
                packed[i // 8] |= 1 << (i % 8)
        return self.exchange_raw(struct.pack('>BHHB', 15, addr, len(states), len(packed))
                                 + bytes(packed))


class ModbusError(Exception):
    def __init__(self, code, req, resp):
        self.code, self.request, self.response = code, req, resp
        names = {1: 'fonction illégale', 2: 'adresse illégale',
                 3: 'valeur illégale', 4: 'commande impossible'}
        super().__init__(f'Exception Modbus {code:02X} ({names.get(code, "erreur")})')
