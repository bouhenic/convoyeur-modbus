"""Robot Niryo Ned2 virtuel : cinématique, mouvements et serveur Modbus TCP.

La table Modbus reproduit celle du firmware Niryo (paquet ``niryo_robot_modbus``
du dépôt NiryoRobotics/ned_ros, serveur sur le port 5020) pour un Ned2 équipé
d'une pince, sans convoyeur Niryo ni caméra. Les réels sont des float32
IEEE 754 sur deux registres, mot de poids fort en premier (big-endian).
Angles en radians, positions en mètres.

Bibliothèque standard uniquement.
"""
import math
import struct
import threading
import time

PORT_NED2 = 5020
PI = math.pi

# ---------------------------------------------------------------------------
# Cinématique — géométrie de l'URDF niryo_ned2 (niryo_robot_description)
# ---------------------------------------------------------------------------


def _rpy(r, p, y):
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr]]


def _tf(xyz, rpy):
    r = _rpy(*rpy)
    return [r[0] + [xyz[0]], r[1] + [xyz[1]], r[2] + [xyz[2]], [0.0, 0.0, 0.0, 1.0]]


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


# Origine de chaque articulation (xyz, rpy) relativement au maillon parent.
CHAIN = [((0, 0, 0.1013), (0, 0, 0)),
         ((0, 0, 0.065), (PI / 2, 0, 0)),
         ((0.012, 0.221, 0), (0, 0, PI / 2)),
         ((0.0325, -0.065, 0), (PI / 2, 0, 0)),
         ((0, 0, 0.17), (-PI / 2, 0, 0)),
         ((0.00925, -0.0197, 0), (PI / 2, 0, 0))]
CHAIN_TF = [_tf(xyz, rpy) for xyz, rpy in CHAIN]
TOOL_TF = _tf((0, 0, 0.0285), (PI, -PI / 2, 0))   # hand_link -> tool_link
LIMITS_DEG = [(-171.88, 171.88), (-105.0, 34.96), (-76.78, 85.5),
              (-119.75, 119.75), (-110.01, 110.17), (-144.96, 144.96)]
LIMITS = [(math.radians(a), math.radians(b)) for a, b in LIMITS_DEG]
HOME = [0.0, 0.5, -1.25, 0.0, 0.0, 0.0]          # position de repos Niryo


def _rz(q):
    c, s = math.cos(q), math.sin(q)
    return [[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def frames(joints, tcp=None):
    """Points des articulations (pour le dessin) et matrice de l'outil."""
    m = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
    points = [(0.0, 0.0, 0.0)]
    for tf, q in zip(CHAIN_TF, joints):
        m = _mul(_mul(m, tf), _rz(q))
        points.append((m[0][3], m[1][3], m[2][3]))
    m = _mul(m, TOOL_TF)
    if tcp is not None:
        m = _mul(m, _tf(tcp[:3], tcp[3:]))
    points.append((m[0][3], m[1][3], m[2][3]))
    return points, m


def matrix_to_pose(m):
    pitch = math.asin(max(-1.0, min(1.0, -m[2][0])))
    if math.cos(pitch) < 1e-3:
        # Blocage de cardan (pince verticale) : roll et yaw ne sont plus
        # séparables ; on fixe roll = 0 et on reporte toute la rotation sur yaw.
        roll = 0.0
        yaw = math.atan2(-m[0][1], m[1][1])
    else:
        roll = math.atan2(m[2][1], m[2][2])
        yaw = math.atan2(m[1][0], m[0][0])
    return [m[0][3], m[1][3], m[2][3], roll + 0.0, pitch, yaw + 0.0]


def forward(joints, tcp=None):
    """Pose [x, y, z, roll, pitch, yaw] de l'outil (m, rad)."""
    return matrix_to_pose(frames(joints, tcp)[1])


def _error(joints, target_m, tcp):
    m = frames(joints, tcp)[1]
    e = [target_m[i][3] - m[i][3] for i in range(3)]
    rot = [0.0, 0.0, 0.0]
    for c in range(3):      # 0,5 · Σ (colonne actuelle × colonne visée)
        a = [m[0][c], m[1][c], m[2][c]]
        b = [target_m[0][c], target_m[1][c], target_m[2][c]]
        rot[0] += .5 * (a[1] * b[2] - a[2] * b[1])
        rot[1] += .5 * (a[2] * b[0] - a[0] * b[2])
        rot[2] += .5 * (a[0] * b[1] - a[1] * b[0])
    return e + rot


def _solve(a, b):
    n = len(b)
    a = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[piv] = a[piv], a[col]
        for r in range(n):
            if r != col and a[col][col]:
                f = a[r][col] / a[col][col]
                for k in range(col, n + 1):
                    a[r][k] -= f * a[col][k]
    return [a[i][n] / a[i][i] if a[i][i] else 0.0 for i in range(n)]


def _clamp(joints):
    return [min(hi, max(lo, q)) for q, (lo, hi) in zip(joints, LIMITS)]


def inverse(pose, seed, tcp=None):
    """Cinématique inverse numérique (moindres carrés amortis).
    Renvoie les 6 angles, ou None si la pose est inaccessible."""
    target = _tf(pose[:3], pose[3:])
    facing = [math.atan2(pose[1], pose[0])] + HOME[1:]
    for start in (seed, facing, HOME, [0.0, 0.0, 0.0, 0.0, -0.5, 0.0]):
        q = _clamp(list(start))
        for _ in range(150):
            e = _error(q, target, tcp)
            if math.hypot(*e[:3]) < 2e-4 and math.hypot(*e[3:]) < 2e-3:
                # Le produit vectoriel s'annule aussi pour un demi-tour :
                # vérifier que les axes pointent bien dans le même sens.
                m = frames(q, tcp)[1]
                if all(sum(m[r][c] * target[r][c] for r in range(3)) > 0.5 for c in range(3)):
                    return q
                break
            h = 1e-5
            jac = [[0.0] * 6 for _ in range(6)]
            for j in range(6):
                dq = q[:]
                dq[j] += h
                ej = _error(dq, target, tcp)
                for i in range(6):
                    jac[i][j] = (e[i] - ej[i]) / h
            lam2 = 0.01 ** 2
            jjt = [[sum(jac[i][k] * jac[j][k] for k in range(6)) + (lam2 if i == j else 0)
                    for j in range(6)] for i in range(6)]
            y = _solve(jjt, e)
            step = [sum(jac[i][j] * y[i] for i in range(6)) for j in range(6)]
            q = _clamp([qi + si for qi, si in zip(q, step)])
    return None


# ---------------------------------------------------------------------------
# Cellule : position du convoyeur et des bacs dans le repère du robot
# ---------------------------------------------------------------------------

PICK_X = 0.25          # le tapis passe devant le robot, parallèle à l'axe Y
CONV_LEN = 0.60        # position 1.0 du convoyeur = y 0 ; position 0 = y 0,60
BELT_Z = 0.06          # dessus du tapis
BOX = 0.04             # cartons cubiques de 4 cm
BOX_Z = BELT_Z + BOX / 2
BINS = {'A': (0.0, 0.25), 'B': (0.0, -0.25)}
BIN_HALF = 0.07
FINGER = 0.075         # bout des doigts de la pince, le long de l'axe X outil
DOWN = PI / 2          # pitch = π/2 : pince verticale, vers le bas

POSES = {
    'au-dessus prise': [PICK_X, 0.0, BOX_Z + FINGER + 0.08, 0.0, DOWN, 0.0],
    'prise': [PICK_X, 0.0, BOX_Z + FINGER, 0.0, DOWN, 0.0],
    'bac A': [0.0, 0.25, 0.22, 0.0, DOWN, PI / 2],
    'bac B': [0.0, -0.25, 0.22, 0.0, DOWN, -PI / 2],
}


def box_xyz(pos):
    return (PICK_X, (1.0 - pos) * CONV_LEN, BOX_Z)


class RobotError(Exception):
    """Commande refusée : équivalent de NiryoRosWrapperException (résultat 2)."""


# ---------------------------------------------------------------------------
# Robot
# ---------------------------------------------------------------------------

class RobotNed2:
    TOOL_ID = 11            # Gripper 1
    BASE_SPEED = 1.0        # rad/s à 100 %
    LINEAR_SPEED = 0.20     # m/s à 100 %

    def __init__(self):
        self.lock = threading.RLock()
        self.done = threading.Condition(self.lock)
        self.conveyor = None
        self.reset()

    def reset(self):
        with self.lock:
            self.joints = list(HOME)
            self.joint_target = [0.0] * 6
            self.pose_target = [0.0] * 6
            self.move_type = 0
            self.blocking = True
            self.tcp_enabled = False
            self.tcp = [0.0] * 6
            self.gripper_closed = False
            self.gripper = 0.0             # 0 ouverte … 1 fermée (animation)
            self.gripper_params = [500, 100, 20, 500, 100, 50]
            self.arm_speed = 100
            self.learning = False
            self.calibration_needed = False
            self.calibrating = 0.0
            self.collision = False
            self.executing = False
            self.last_result = 0
            self.digital_outputs = [False] * 4
            self.analog_outputs = [0.0] * 2
            self.user_coils = [False] * 100
            self.user_floats = [0.0] * 100
            self.user_ints = [0] * 100
            self.relative = [0.0] * 3
            self.workspace = ''
            self.vision_params = [0, 0, 0]  # hauteur, forme, couleur
            self.motion = None
            self.held = False
            self.bins = {'A': 0, 'B': 0, 'sol': 0}
            self.program = None
            self.program_text = 'Programme arrêté'
            self.message = ''
            self.simtime = 0.0

    # ----- lecture d'état -----
    def tcp_or_none(self):
        return self.tcp if self.tcp_enabled else None

    def pose(self):
        with self.lock:
            return forward(self.joints, self.tcp_or_none())

    def fingertip(self):
        _, m = frames(self.joints)
        return tuple(m[i][3] + FINGER * m[i][0] for i in range(3))

    def moving(self):
        return self.motion is not None

    def digital_inputs(self):
        s2 = bool(self.conveyor and self.conveyor.box_at_end())
        return [s2, False, False, False, False]

    def estop(self):
        return bool(self.conveyor and self.conveyor.estop_pressed)

    def snapshot(self):
        with self.lock:
            points, m = frames(self.joints)
            axes = [[m[r][c] for r in range(3)] for c in range(3)]   # X, Y, Z outil
            return dict(joints=list(self.joints), pose=self.pose(), points=points, axes=axes,
                        fingertip=self.fingertip(), gripper=self.gripper,
                        gripper_closed=self.gripper_closed, held=self.held,
                        moving=self.moving(), collision=self.collision,
                        executing=self.executing, last_result=self.last_result,
                        learning=self.learning, calibrating=self.calibrating > 0,
                        calibration_needed=self.calibration_needed,
                        bins=dict(self.bins), program=self.program is not None,
                        program_text=self.program_text, message=self.message,
                        speed=self.arm_speed, di=self.digital_inputs(),
                        blocking=self.blocking, user_ints=self.user_ints[:2],
                        pause=self.user_coils[0])

    # ----- mouvements -----
    def _check_can_move(self, from_program=False):
        if self.program is not None and not from_program:
            raise RobotError('programme embarqué en cours')
        if self.estop():
            raise RobotError('arrêt d’urgence actif')
        if self.collision:
            raise RobotError('collision détectée : effacer la coil 117')
        if self.calibration_needed or self.calibrating > 0:
            raise RobotError('calibration nécessaire')
        if self.motion is not None:
            raise RobotError('un mouvement est déjà en cours')

    def start_move(self, kind, target, from_program=False):
        """kind : 0 = MOVE_JOINT, 1 = MOVE_POSE, 2 = MOVE_LINEAR."""
        with self.lock:
            self._check_can_move(from_program)
            factor = max(self.arm_speed, 1) / 100
            start = list(self.joints)
            if kind == 0:
                goal = [float(v) for v in target]
                for q, (lo, hi) in zip(goal, LIMITS):
                    if not lo - 1e-6 <= q <= hi + 1e-6:
                        raise RobotError('cible hors des limites articulaires')
                path = [start, goal]
            elif kind == 1:
                goal = inverse(target, start, self.tcp_or_none())
                if goal is None:
                    raise RobotError('pose inaccessible')
                path = [start, goal]
            elif kind == 2:
                p0 = forward(start, self.tcp_or_none())
                dist = math.dist(p0[:3], target[:3])
                steps = max(2, int(dist / 0.005))
                path, seed = [start], start
                for k in range(1, steps + 1):
                    t = k / steps
                    yaw0, yaw1 = p0[5], target[5]
                    dyaw = (yaw1 - yaw0 + PI) % (2 * PI) - PI
                    p = [a + (b - a) * t for a, b in zip(p0[:5], target[:5])] + [yaw0 + dyaw * t]
                    q = inverse(p, seed, self.tcp_or_none())
                    if q is None or max(abs(a - b) for a, b in zip(q, seed)) > 0.5:
                        raise RobotError('trajectoire linéaire impossible')
                    path.append(q)
                    seed = q
            else:
                raise RobotError(f'type de mouvement inconnu : {kind}')
            if kind == 2:
                duration = max(0.3, dist / (self.LINEAR_SPEED * factor))
            else:
                duration = max(0.3, max(abs(a - b) for a, b in zip(path[0], path[-1]))
                               / (self.BASE_SPEED * factor))
            self.learning = False
            self.motion = dict(path=path, t=0.0, duration=duration)
            self.message = ''

    def stop_move(self):
        with self.lock:
            self.motion = None
            self.done.notify_all()

    def wait_motion(self, timeout=60.0):
        end = time.monotonic() + timeout
        with self.lock:
            while self.motion is not None and time.monotonic() < end:
                self.done.wait(0.1)
            if self.collision:
                raise RobotError('mouvement interrompu par une collision')

    def simulate_collision(self):
        with self.lock:
            if self.motion is not None:
                self.motion = None
                self.collision = True
                self.message = 'Collision détectée : mouvement arrêté'
                self.done.notify_all()
            else:
                self.collision = True

    # ----- pince -----
    def set_gripper(self, closed):
        with self.lock:
            if self.program is not None:
                raise RobotError('programme embarqué en cours')
            self._actuate(closed)

    def _actuate(self, closed):
        self.gripper_closed = bool(closed)
        tip = self.fingertip()
        if closed and not self.held and self.conveyor is not None:
            for index, pos in self.conveyor.box_positions():
                if math.dist(tip, box_xyz(pos)) < 0.03:
                    self.conveyor.take_box(index)
                    self.held = True
                    self.message = 'Carton saisi'
                    break
        elif not closed and self.held:
            self.held = False
            x, y, _ = tip
            for name, (bx, by) in BINS.items():
                if abs(x - bx) < BIN_HALF and abs(y - by) < BIN_HALF:
                    self.bins[name] += 1
                    self.message = f'Carton déposé dans le bac {name}'
                    break
            else:
                self.bins['sol'] += 1
                self.message = 'Carton lâché hors des bacs'

    # ----- programme embarqué -----
    def start_program(self):
        with self.lock:
            if self.program is None:
                self.program = self._program()
                self.program_text = 'Programme démarré'

    def stop_program(self):
        with self.lock:
            self.program = None
            self.motion = None
            self.program_text = 'Programme arrêté'
            self.done.notify_all()

    def _wait_move(self, kind, target, text):
        self.program_text = text
        self.start_move(kind, target, from_program=True)
        while self.motion is not None:
            yield

    def _wait(self, seconds):
        end = self.simtime + seconds
        while self.simtime < end:
            yield

    def _program(self):
        """Prise sur le convoyeur, dépose dans le bac choisi par HR 400.
        Coil 200 = pause ; HR 401 = pièces déposées (zone utilisateur Niryo)."""
        self._actuate(False)
        yield from self._wait_move(0, HOME, 'Départ en position home')
        while True:
            while self.user_coils[0]:
                self.program_text = 'Pause (coil 200 = 1)'
                yield
            yield from self._wait_move(1, POSES['au-dessus prise'], 'Approche de la prise')
            while not self.digital_inputs()[0] and not self.user_coils[0]:
                self.program_text = 'Attente d’un carton (DI1)'
                yield
            if not self.digital_inputs()[0]:
                continue
            yield from self._wait_move(2, POSES['prise'], 'Descente sur le carton')
            self._actuate(True)
            yield from self._wait(0.3)
            yield from self._wait_move(2, POSES['au-dessus prise'], 'Dégagement')
            name = 'B' if self.user_ints[0] == 1 else 'A'
            yield from self._wait_move(1, POSES[f'bac {name}'], f'Transport vers le bac {name}')
            self._actuate(False)
            self.user_ints[1] = (self.user_ints[1] + 1) & 0xFFFF
            yield from self._wait(0.3)

    # ----- horloge -----
    def advance(self, dt):
        dt = max(0.0, min(dt, 0.2))
        with self.lock:
            self.simtime += dt
            if self.estop() and (self.motion is not None or self.program is not None):
                self.motion = None
                self.program = None
                self.program_text = 'Programme arrêté (arrêt d’urgence)'
                self.message = 'Arrêt d’urgence : robot stoppé'
                self.done.notify_all()
            target = 1.0 if self.gripper_closed else 0.0
            self.gripper += max(-dt * 3, min(dt * 3, target - self.gripper))
            if self.calibrating > 0:
                self.calibrating = max(0.0, self.calibrating - dt)
                if self.calibrating == 0:
                    self.calibration_needed = False
            if self.motion is not None:
                m = self.motion
                m['t'] += dt
                u = min(1.0, m['t'] / m['duration'])
                s = u * u * (3 - 2 * u)            # départ et arrivée en douceur
                path = m['path']
                f = s * (len(path) - 1)
                i = min(int(f), len(path) - 2)
                w = f - i
                self.joints = [a + (b - a) * w for a, b in zip(path[i], path[i + 1])]
                if u >= 1.0:
                    self.joints = list(path[-1])
                    self.motion = None
                    self.done.notify_all()
            if self.program is not None:
                try:
                    next(self.program)
                except RobotError as exc:
                    self.program = None
                    self.program_text = f'Programme interrompu : {exc}'
                except StopIteration:
                    self.program = None


robot = RobotNed2()


# ---------------------------------------------------------------------------
# Table Modbus Niryo (adresses identiques au firmware)
# ---------------------------------------------------------------------------

class Entry:
    def __init__(self, name, start, count, kind, get, set_=None):
        self.name, self.start, self.count, self.kind = name, start, count, kind
        self.get, self.set = get, set_
        self.width = 2 if kind == 'float' else 1

    def encode(self, i):
        value = self.get(i)
        if self.kind == 'float':
            return list(struct.unpack('>HH', struct.pack('>f', float(value))))
        if self.kind == 'str':
            raw = value.encode('ascii', 'replace')[:2].ljust(2, b'\x00')
            return [struct.unpack('>H', raw)[0]]
        return [int(value) & 0xFFFF]

    def decode(self, regs):
        if self.kind == 'float':
            return struct.unpack('>f', struct.pack('>HH', *regs))[0]
        if self.kind == 'str':
            return struct.pack('>H', regs[0]).decode('ascii', 'replace').rstrip('\x00')
        return regs[0]


def _slot(obj, attr, conv=lambda v: v):
    def setter(i, v):
        getattr(obj, attr)[i] = conv(v)
    return setter


def _build_tables(r):
    def blocking_move(_i, value):
        if not value:
            r.stop_move()
            return
        with r.lock:
            if r.move_type == 0:
                target = list(r.joint_target)
            else:
                target = list(r.pose_target)
            r.start_move(r.move_type, target)
            blocking = r.blocking
        if blocking:
            r.wait_motion()

    def gripper(_i, value):
        r.set_gripper(value)
        time.sleep(0.5)          # grasp / release sont bloquants sur le robot

    def tcp_set(i, v):
        r.tcp[i] = v

    def tcp_enable(_i, v):
        r.tcp_enabled = bool(v)

    def learning(_i, v):
        if v and r.moving():
            raise RobotError('robot en mouvement')
        r.learning = bool(v)

    def calib_needed(_i, v):
        if v:
            r.calibration_needed = True

    def calibrate(_i, v):
        if v and r.calibration_needed:
            if r.moving():
                raise RobotError('robot en mouvement')
            r.calibrating = 3.0
            r.joints = list(HOME)

    def collision(_i, v):
        if not v:
            r.collision = False

    def blocking(_i, v):
        r.blocking = bool(v)

    def move_type(_i, v):
        if v not in (0, 1, 2):
            raise ValueError('type de mouvement inconnu')
        r.move_type = v

    def arm_speed(_i, v):
        if not 1 <= v <= 200:
            raise RobotError('vitesse hors limites')
        r.arm_speed = v

    def workspace_set(i, v):
        name = r.workspace.ljust(i * 2)
        r.workspace = (name[:i * 2] + v + name[i * 2 + 2:]).rstrip()

    def ro(value):
        return lambda i: value

    zero = ro(0)
    pose_of = lambda i: r.pose()[i]
    version = [5, 6, 0, 0]
    hw = 'ned2'
    coils = [
        Entry('DO1–DO4 (sorties TOR)', 0, 4, 'bool', lambda i: r.digital_outputs[i],
              _slot(r, 'digital_outputs', bool)),
        Entry('Outil équipé', 50, 1, 'bool', lambda i: True, lambda i, v: None),
        Entry('Pince (1 = fermer / saisir)', 51, 1, 'bool', lambda i: r.gripper_closed, gripper),
        Entry('TCP activé', 52, 1, 'bool', lambda i: r.tcp_enabled, tcp_enable),
        Entry('Robot en mouvement / lancer le mouvement', 113, 1, 'bool',
              lambda i: r.moving(), blocking_move),
        Entry('Mode apprentissage', 114, 1, 'bool', lambda i: r.learning, learning),
        Entry('Calibration nécessaire', 115, 1, 'bool', lambda i: r.calibration_needed, calib_needed),
        Entry('Calibration en cours', 116, 1, 'bool', lambda i: r.calibrating > 0, calibrate),
        Entry('Collision détectée', 117, 1, 'bool', lambda i: r.collision, collision),
        Entry('Mouvements bloquants', 118, 1, 'bool', lambda i: r.blocking, blocking),
        Entry('Zone utilisateur (bits)', 200, 100, 'bool', lambda i: r.user_coils[i],
              _slot(r, 'user_coils', bool)),
    ]
    discretes = [
        Entry('DI1–DI5 (entrées TOR)', 0, 5, 'bool', lambda i: r.digital_inputs()[i]),
        Entry('Moteurs connectés', 50, 1, 'bool', lambda i: True),
        Entry('Commande en cours d’exécution', 51, 1, 'bool', lambda i: r.executing),
        Entry('Cible vision trouvée', 52, 1, 'bool', lambda i: False),
    ]
    holding = [
        Entry('AO1–AO2 (V)', 0, 2, 'float', lambda i: r.analog_outputs[i], _slot(r, 'analog_outputs')),
        Entry('Cible articulaire J1–J6 (rad)', 50, 6, 'float', lambda i: r.joint_target[i],
              _slot(r, 'joint_target')),
        Entry('Cible en pose x y z (m) r p y (rad)', 62, 6, 'float', lambda i: r.pose_target[i],
              _slot(r, 'pose_target')),
        Entry('Type de mouvement (0 J, 1 P, 2 L)', 74, 1, 'int', lambda i: r.move_type, move_type),
        Entry('Transformation TCP', 75, 6, 'float', lambda i: r.tcp[i], tcp_set),
        Entry('Réglages pince', 107, 6, 'int', lambda i: r.gripper_params[i], _slot(r, 'gripper_params')),
        Entry('Relatif x y yaw (vision)', 113, 3, 'float', lambda i: r.relative[i], _slot(r, 'relative')),
        Entry('Nom de l’espace de travail', 119, 20, 'str',
              lambda i: r.workspace[i * 2:i * 2 + 2], workspace_set),
        Entry('Vision : hauteur, forme, couleur', 139, 3, 'int', lambda i: r.vision_params[i],
              _slot(r, 'vision_params')),
        Entry('Vitesse du bras (%)', 142, 1, 'int', lambda i: r.arm_speed, arm_speed),
        Entry('Zone utilisateur (float32)', 200, 100, 'float', lambda i: r.user_floats[i],
              _slot(r, 'user_floats')),
        Entry('Zone utilisateur (entiers)', 400, 100, 'int', lambda i: r.user_ints[i],
              _slot(r, 'user_ints')),
    ]
    inputs = [
        Entry('AI1–AI2 (V)', 0, 2, 'float', ro(0.0)),
        Entry('Position articulaire J1–J6 (rad)', 50, 6, 'float', lambda i: r.joints[i]),
        Entry('Pose x y z (m) r p y (rad)', 62, 6, 'float', pose_of),
        Entry('Pose absolue depuis relatif', 74, 6, 'float', ro(0.0)),
        Entry('Pose de la cible vision', 86, 6, 'float', ro(0.0)),
        Entry('Forme / couleur vision', 98, 2, 'int', zero),
        Entry('Résultat de la dernière commande', 120, 1, 'int', lambda i: r.last_result),
        Entry('ID de l’outil', 121, 1, 'int', lambda i: r.TOOL_ID),
        Entry('Température Raspberry (°C)', 122, 1, 'int', ro(46)),
        Entry('Espace disque libre (Mo)', 123, 1, 'int', ro(12000)),
        Entry('Taille des logs (Mo)', 124, 1, 'int', ro(18)),
        Entry('Version matérielle', 125, 2, 'str', lambda i: hw[i * 2:i * 2 + 2]),
        Entry('Version système (majeur, mineur, correctif, build)', 129, 4, 'int',
              lambda i: version[i]),
    ]
    tables = {}
    for fc, entries in ((1, coils), (2, discretes), (3, holding), (4, inputs)):
        amap = {}
        for e in entries:
            for i in range(e.count):
                for half in range(e.width):
                    amap[e.start + i * e.width + half] = (e, i, half)
        tables[fc] = amap
    tables[5] = tables[15] = tables[1]
    tables[6] = tables[16] = tables[3]
    return tables


TABLES = _build_tables(robot)
LIST_TABLES = {1: 'coils', 2: 'entrées TOR', 3: 'holding registers', 4: 'input registers'}


def _exception(fc, code):
    return bytes([fc | 0x80, code])


def _apply(entry, index, value):
    """Écriture : comme le firmware, une erreur ne produit pas d'exception
    Modbus ; elle est seulement visible dans IR 120 (dernier résultat)."""
    with robot.lock:
        robot.executing = True
    try:
        entry.set(index, value)
        result = 0
    except RobotError as exc:
        result = 2
        with robot.lock:
            robot.message = f'Commande refusée : {exc}'
    except (ValueError, TypeError) as exc:
        result = 1
        with robot.lock:
            robot.message = f'Commande refusée : {exc}'
    finally:
        with robot.lock:
            robot.executing = False
    with robot.lock:
        robot.last_result = result


def _read(fc, addr, qty):
    table = TABLES[fc]
    if any(a not in table for a in range(addr, addr + qty)):
        return None
    values = []
    with robot.lock:
        for a in range(addr, addr + qty):
            entry, i, half = table[a]
            values.append(entry.encode(i)[half])
    return values


def process_pdu_robot(pdu):
    if not pdu:
        return b''
    fc = pdu[0]
    if fc not in (1, 2, 3, 4, 5, 6, 15, 16):
        return _exception(fc, 1)
    if fc in (1, 2, 3, 4, 5, 6):
        if len(pdu) != 5:
            return _exception(fc, 3)
        addr, value = struct.unpack('>HH', pdu[1:5])
    if fc in (1, 2, 3, 4):
        max_qty = 2000 if fc in (1, 2) else 125
        if not 1 <= value <= max_qty:
            return _exception(fc, 3)
        values = _read(fc, addr, value)
        if values is None:
            return _exception(fc, 2)
        if fc in (1, 2):
            packed = bytearray((len(values) + 7) // 8)
            for i, bit in enumerate(values):
                if bit:
                    packed[i // 8] |= 1 << (i % 8)
            return bytes((fc, len(packed))) + bytes(packed)
        return bytes((fc, 2 * len(values))) + b''.join(struct.pack('>H', v) for v in values)
    if fc == 5:
        if value not in (0, 0xFF00):
            return _exception(fc, 3)
        if addr not in TABLES[5]:
            return _exception(fc, 2)
        entry, i, _ = TABLES[5][addr]
        _apply(entry, i, value == 0xFF00)
        return pdu
    if fc == 6:
        if addr not in TABLES[6]:
            return _exception(fc, 2)
        entry, i, _ = TABLES[6][addr]
        if entry.width == 2:
            # Un float32 occupe deux registres : le firmware ne sait pas décoder
            # un seul mot et ignore l'écriture, sans exception Modbus.
            return pdu
        _apply(entry, i, entry.decode([value]))
        return pdu
    # FC15 / FC16 : adresse, quantité, nombre d'octets, données
    if len(pdu) < 6:
        return _exception(fc, 3)
    addr, qty, nbytes = struct.unpack('>HHB', pdu[1:6])
    data = pdu[6:]
    if fc == 15:
        if not 1 <= qty <= 1968 or nbytes != (qty + 7) // 8 or len(data) != nbytes:
            return _exception(fc, 3)
        if any(a not in TABLES[15] for a in range(addr, addr + qty)):
            return _exception(fc, 2)
        for k in range(qty):
            entry, i, _ = TABLES[15][addr + k]
            _apply(entry, i, bool((data[k // 8] >> (k % 8)) & 1))
        return struct.pack('>BHH', fc, addr, qty)
    if not 1 <= qty <= 123 or nbytes != 2 * qty or len(data) != nbytes:
        return _exception(fc, 3)
    if any(a not in TABLES[16] for a in range(addr, addr + qty)):
        return _exception(fc, 2)
    regs = list(struct.unpack('>' + 'H' * qty, data))
    a, k = addr, 0
    while k < qty:
        entry, i, _ = TABLES[16][a]
        chunk = regs[k:k + entry.width]
        if len(chunk) < entry.width:
            break                      # float incomplet : ignoré, comme le firmware
        _apply(entry, i, entry.decode(chunk))
        a += entry.width
        k += entry.width
    return struct.pack('>BHH', fc, addr, qty)


def describe_robot(pdu):
    """Explication en français d'une requête destinée au Ned2."""
    if not pdu:
        return 'Trame vide'
    fc = pdu[0]
    names = {1: 'Lire coils', 2: 'Lire entrées TOR', 3: 'Lire holding registers',
             4: 'Lire input registers', 5: 'Écrire coil', 6: 'Écrire registre',
             15: 'Écrire plusieurs coils', 16: 'Écrire plusieurs registres'}
    if fc not in names or len(pdu) < 5:
        return f'Ned2 · fonction {fc} non prise en charge'
    addr, value = struct.unpack('>HH', pdu[1:5])
    table = TABLES.get(fc, {})
    what = table[addr][0].name if addr in table else 'adresse non attribuée'
    if fc in (1, 2, 3, 4):
        return f'Ned2 · {names[fc]} · adresse {addr} × {value} · {what}'
    if fc == 5:
        return f'Ned2 · {names[fc]} {addr} = {1 if value == 0xFF00 else 0} · {what}'
    if fc == 6:
        return f'Ned2 · {names[fc]} {addr} = {value} · {what}'
    return f'Ned2 · {names[fc]} · adresse {addr} × {value} · {what}'


def floats_to_regs(values):
    regs = []
    for v in values:
        regs += list(struct.unpack('>HH', struct.pack('>f', float(v))))
    return regs


def regs_to_floats(regs):
    return [struct.unpack('>f', struct.pack('>HH', regs[i], regs[i + 1]))[0]
            for i in range(0, len(regs) - 1, 2)]
