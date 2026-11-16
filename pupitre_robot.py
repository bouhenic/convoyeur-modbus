#!/usr/bin/env python3
"""Pupitre du robot Ned2 : client Modbus TCP (table Niryo, port 5020).

Fonctionne avec le robot virtuel du simulateur, et avec un vrai Ned2 :
    python3 pupitre_robot.py --host <IP du robot>
Simulateur sur une autre machine : --host <IP du simulateur>, ou champ « Serveur ».
"""
import argparse
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from bouton import BoutonPlat
from cible import BarreServeur, Cible, message_erreur
from decodeur import decode_pair
from modbus_core import ModbusError, ModbusTcpClient, hx
from robot_ned2 import HOME, PORT_NED2, POSES, floats_to_regs, regs_to_floats

BG = '#101827'; PANEL = '#192638'; PANEL2 = '#223248'
WHITE = '#eef5ff'; MUTED = '#9cafc5'; GREEN = '#4bd6a0'
RED = '#ff7286'; BLUE = '#71b9ff'; ORANGE = '#ffbd6c'
FONT = 'Arial'
RESULTS = {0: '0 · OK', 1: '1 · erreur Modbus', 2: '2 · erreur robot'}
MOVES = {0: 'MOVE_J', 1: 'MOVE_P', 2: 'MOVE_L'}


def label(p, text, size=10, bold=False, fg=WHITE, bg=PANEL, **kw):
    return tk.Label(p, text=text, bg=bg, fg=fg, font=(FONT, size, 'bold' if bold else 'normal'), **kw)


def btn(p, text, command, bg=PANEL2):
    return BoutonPlat(p, text, command, bg=bg, fg=WHITE, font=(FONT, 10, 'bold'), padx=12, pady=8)


def field(parent, var, width=8):
    return tk.Entry(parent, textvariable=var, width=width, bg='#0d1825', fg=WHITE, relief='flat',
                    insertbackground=WHITE, font=('Courier', 11), justify='right')


class CommandWorker(threading.Thread):
    """Exécute les séquences de commandes sur sa propre connexion.
    Un mouvement bloquant peut durer plusieurs secondes : délai de 30 s."""
    def __init__(self, cible, commands, updates, stop):
        super().__init__(daemon=True)
        self.client = ModbusTcpClient(timeout=30)
        self.cible, self.vue = cible, -1
        self.commands, self.updates, self.stop = commands, updates, stop

    def run(self):
        while not self.stop.is_set():
            try:
                steps = self.commands.get(timeout=0.2)
            except queue.Empty:
                continue
            self.vue, _ = self.cible.suivre(self.client, self.vue)
            for text, action in steps:
                stamp = time.strftime('%H:%M:%S')
                try:
                    result = action(self.client)
                    _, request, response = result
                    self.updates.put(('trace', stamp, text, hx(request), hx(response), 'OK'))
                    if text.startswith('FC04 • Résultat'):
                        self.updates.put(('result', result[0][0]))
                except ModbusError as exc:
                    self.updates.put(('trace', stamp, text, hx(exc.request), hx(exc.response),
                                      f'EXCEPTION {exc.code:02X}'))
                    self.updates.put(('note', f'{text} → {exc}', RED))
                    break
                except (OSError, ValueError, ConnectionError) as exc:
                    self.client.close()
                    self.updates.put(('note', f'{text} → connexion : {exc}', RED))
                    break


class PollWorker(threading.Thread):
    """Lecture périodique de l'état du robot, sur une seconde connexion."""
    READS = [(4, 50, 24, 'FC04 • Joints et pose (IR 50–73)'),
             (4, 120, 2, 'FC04 • Résultat et outil (IR 120–121)'),
             (1, 113, 6, 'FC01 • États (coils 113–118)'),
             (1, 51, 1, 'FC01 • Pince (coil 51)'),
             (2, 0, 5, 'FC02 • DI1–DI5'),
             (2, 50, 2, 'FC02 • Moteurs, commande en cours'),
             (3, 142, 1, 'FC03 • Vitesse du bras (HR 142)'),
             (3, 400, 2, 'FC03 • Zone utilisateur HR 400–401')]

    def __init__(self, cible, updates, enabled, trace, stop):
        super().__init__(daemon=True)
        self.client = ModbusTcpClient(timeout=2)
        self.cible, self.vue = cible, -1
        self.updates, self.enabled, self.trace, self.stop = updates, enabled, trace, stop

    def run(self):
        last_error = None
        while not self.stop.is_set():
            self.vue, changee = self.cible.suivre(self.client, self.vue)
            if changee:
                last_error = None
                self.updates.put(('connection', None,
                                  f'Connexion à {self.client.host}:{self.client.port}…'))
            if not self.enabled.is_set():
                self.stop.wait(0.2)
                continue
            try:
                if self.client.sock is None:
                    self.client.connect()
                    self.updates.put(('connection', True,
                                      f'Connecté à {self.client.host}:{self.client.port}'))
                    last_error = None
                data = {}
                for fc, addr, n, text in self.READS:
                    values, req, resp = self.client.read(fc, addr, n)
                    data[(fc, addr)] = values
                    if self.trace.is_set():
                        self.updates.put(('trace', time.strftime('%H:%M:%S'), text, hx(req), hx(resp), 'OK'))
                self.updates.put(('poll', data))
            except ModbusError as exc:
                self.updates.put(('note', f'Lecture refusée : {exc}', RED))
            except (OSError, ValueError, ConnectionError) as exc:
                self.client.close()
                err = message_erreur(exc)
                if err != last_error:
                    self.updates.put(('connection', False, f'Échec : {err}'))
                    last_error = err
                self.stop.wait(1.0)
                continue
            self.stop.wait(0.8)
        self.client.close()


class RobotPanel:
    def __init__(self, root, host, port):
        self.root = root
        self.commands, self.updates = queue.Queue(), queue.Queue()
        self.stop = threading.Event()
        self.poll_on, self.trace_poll = threading.Event(), threading.Event()
        self.poll_on.set()
        self.rows = {}
        self.last = {}
        self.cible = Cible(host, port)
        root.title('MODBUS LAB — Pupitre robot Ned2 (client)')
        root.geometry('1080x830')
        root.minsize(980, 760)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Lab.Treeview', background=PANEL, fieldbackground=PANEL, foreground=WHITE,
                        rowheight=24, borderwidth=0, font=(FONT, 10))
        style.configure('Lab.Treeview.Heading', background=PANEL2, foreground=WHITE,
                        font=(FONT, 10, 'bold'))
        style.map('Lab.Treeview', background=[('selected', '#2c5e86')])

        head = tk.Frame(root, bg=BG)
        head.pack(fill='x', padx=20, pady=(14, 10))
        label(head, 'PUPITRE ROBOT NED2', 21, True, BLUE, BG).pack(side='left')
        BarreServeur(head, self.cible, lambda _host: None, BG, WHITE, FONT,
                     button_bg=PANEL2).pack(side='left', padx=(22, 0), pady=4)
        self.connected = label(head, f'● Connexion à {host}:{port}…', 11, True, ORANGE, BG)
        self.connected.pack(side='right', pady=6, padx=(12, 0))

        body = tk.Frame(root, bg=BG)
        body.pack(fill='x', padx=20)
        left = tk.Frame(body, bg=BG)
        left.pack(side='left', fill='both', expand=True, padx=(0, 10))
        right = tk.Frame(body, bg=PANEL, width=270)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)

        # --- Mouvement articulaire ---
        jp = tk.Frame(left, bg=PANEL)
        jp.pack(fill='x', pady=(0, 8))
        label(jp, 'MOUVEMENT ARTICULAIRE — HR 50 à 61 · float32 en radians (saisie en degrés)',
              10, True, BLUE).pack(anchor='w', padx=12, pady=(9, 5))
        grid = tk.Frame(jp, bg=PANEL)
        grid.pack(anchor='w', padx=12)
        self.jvars = [tk.StringVar(value=f'{math.degrees(q):.1f}') for q in HOME]
        for i, var in enumerate(self.jvars):
            label(grid, f'J{i + 1}', 10, True, MUTED).grid(row=0, column=2 * i, padx=(0 if i == 0 else 10, 4))
            field(grid, var, 7).grid(row=0, column=2 * i + 1, ipady=3)
        jb = tk.Frame(jp, bg=PANEL)
        jb.pack(anchor='w', padx=8, pady=8)
        btn(jb, 'MOVE_J ▶', lambda: self.move(0), '#126648').pack(side='left', padx=4)
        btn(jb, 'Copier la position actuelle', self.copy_joints).pack(side='left', padx=4)
        btn(jb, 'Home', lambda: self.fill_joints(HOME)).pack(side='left', padx=4)

        # --- Mouvement en pose ---
        pp = tk.Frame(left, bg=PANEL)
        pp.pack(fill='x', pady=(0, 8))
        label(pp, 'MOUVEMENT EN POSE — HR 62 à 73 · x y z en mètres, roll pitch yaw en radians',
              10, True, BLUE).pack(anchor='w', padx=12, pady=(9, 5))
        grid = tk.Frame(pp, bg=PANEL)
        grid.pack(anchor='w', padx=12)
        self.pnames = ['x mm', 'y mm', 'z mm', 'roll °', 'pitch °', 'yaw °']
        self.pvars = [tk.StringVar() for _ in self.pnames]
        for i, (name, var) in enumerate(zip(self.pnames, self.pvars)):
            label(grid, name, 10, True, MUTED).grid(row=0, column=2 * i, padx=(0 if i == 0 else 10, 4))
            field(grid, var, 7).grid(row=0, column=2 * i + 1, ipady=3)
        self.fill_pose(POSES['au-dessus prise'])
        pb = tk.Frame(pp, bg=PANEL)
        pb.pack(anchor='w', padx=8, pady=(8, 4))
        btn(pb, 'MOVE_P ▶', lambda: self.move(1), '#126648').pack(side='left', padx=4)
        btn(pb, 'MOVE_L ▶', lambda: self.move(2), '#255a86').pack(side='left', padx=4)
        btn(pb, 'Copier la pose actuelle', self.copy_pose).pack(side='left', padx=4)
        presets = tk.Frame(pp, bg=PANEL)
        presets.pack(anchor='w', padx=8, pady=(0, 9))
        label(presets, 'Poses de la cellule :', 9, fg=MUTED).pack(side='left', padx=4)
        for name in POSES:
            btn(presets, name, lambda n=name: self.fill_pose(POSES[n])).pack(side='left', padx=3)

        # --- Outil et réglages ---
        tp = tk.Frame(left, bg=PANEL)
        tp.pack(fill='x')
        label(tp, 'PINCE, SÉCURITÉ ET RÉGLAGES', 10, True, BLUE).pack(anchor='w', padx=12, pady=(9, 5))
        row = tk.Frame(tp, bg=PANEL)
        row.pack(anchor='w', padx=8)
        btn(row, 'Ouvrir pince', lambda: self.send([('FC05 • Coil 51 = 0 → ouvrir la pince',
                                                     lambda c: c.write_coil(51, False))])).pack(side='left', padx=4)
        btn(row, 'Fermer pince', lambda: self.send([('FC05 • Coil 51 = 1 → fermer / saisir',
                                                     lambda c: c.write_coil(51, True))])).pack(side='left', padx=4)
        btn(row, '■ STOP', lambda: self.send([('FC05 • Coil 113 = 0 → arrêter le mouvement',
                                              lambda c: c.write_coil(113, False))]), '#8b3848').pack(side='left', padx=4)
        btn(row, 'Effacer collision', lambda: self.send([('FC05 • Coil 117 = 0 → effacer la collision',
                                                         lambda c: c.write_coil(117, False))]),
            '#815025').pack(side='left', padx=4)
        row = tk.Frame(tp, bg=PANEL)
        row.pack(anchor='w', padx=12, pady=(8, 10))
        label(row, 'Vitesse bras (HR 142)', 10).pack(side='left')
        self.speed = tk.StringVar(value='100')
        field(row, self.speed, 5).pack(side='left', padx=5, ipady=3)
        btn(row, 'Envoyer', self.send_speed).pack(side='left', padx=(0, 14))
        self.blocking = tk.BooleanVar(value=True)
        tk.Checkbutton(row, text='Mouvements bloquants (coil 118)', variable=self.blocking,
                       command=self.send_blocking, bg=PANEL, fg=WHITE, activebackground=PANEL,
                       activeforeground=WHITE, selectcolor=BG, font=(FONT, 10)).pack(side='left')
        row = tk.Frame(tp, bg=PANEL)
        row.pack(anchor='w', padx=12, pady=(0, 10))
        label(row, 'Programme embarqué :', 10, fg=MUTED).pack(side='left')
        btn(row, 'Bac A (HR 400 = 0)', lambda: self.send([('FC06 • HR 400 = 0 → bac A',
                                                           lambda c: c.write_register(400, 0))])).pack(side='left', padx=4)
        btn(row, 'Bac B (HR 400 = 1)', lambda: self.send([('FC06 • HR 400 = 1 → bac B',
                                                           lambda c: c.write_register(400, 1))])).pack(side='left', padx=4)
        btn(row, 'Pause (coil 200)', lambda: self.send([('FC05 • Coil 200 = 1 → pause',
                                                         lambda c: c.write_coil(200, True))])).pack(side='left', padx=4)
        btn(row, 'Reprise', lambda: self.send([('FC05 • Coil 200 = 0 → reprise',
                                                lambda c: c.write_coil(200, False))])).pack(side='left', padx=4)

        # --- Valeurs lues ---
        label(right, 'VALEURS LUES', 12, True).pack(anchor='w', padx=12, pady=(10, 6))
        self.values = {}
        # Angles (IR 50–61) et pose (IR 62–73) côte à côte
        pairs = tk.Frame(right, bg=PANEL)
        pairs.pack(fill='x', padx=12, pady=(0, 8))
        pairs.columnconfigure(1, weight=1)
        pairs.columnconfigure(3, weight=1)
        for r, (jn, pn) in enumerate(zip(['J1 °', 'J2 °', 'J3 °', 'J4 °', 'J5 °', 'J6 °'], self.pnames)):
            for c, name in ((0, jn), (2, pn)):
                label(pairs, name, 9, fg=MUTED).grid(row=r, column=c, sticky='w', padx=(0 if c == 0 else 12, 4))
                self.values[name] = label(pairs, '—', 10, True)
                self.values[name].grid(row=r, column=c + 1, sticky='e')
        names = ['En mouvement (c113)', 'Pince fermée (c51)', 'Collision (c117)', 'Commande (DI 51)',
                 'Résultat (IR 120)', 'DI1 carton', 'Outil (IR 121)', 'Vitesse (HR 142)',
                 'Pièces (HR 401)']
        for name in names:
            row = tk.Frame(right, bg=PANEL)
            row.pack(fill='x', padx=12)
            label(row, name, 9, fg=MUTED).pack(side='left')
            self.values[name] = label(row, '—', 10, True)
            self.values[name].pack(side='right')

        # --- Trame manuelle ---
        raw = tk.Frame(root, bg=PANEL)
        raw.pack(fill='x', padx=20, pady=8)
        label(raw, 'PDU MANUELLE', 10, True, BLUE).pack(side='left', padx=12)
        self.raw = tk.StringVar(value='04 00 32 00 0C')
        tk.Entry(raw, textvariable=self.raw, width=44, bg='#0d1825', fg=GREEN, insertbackground=WHITE,
                 relief='flat', font=('Courier', 11)).pack(side='left', padx=8, ipady=6)
        btn(raw, 'Envoyer PDU', self.send_raw, '#265781').pack(side='left', padx=4, pady=6)
        label(raw, 'ex. 04 00 32 00 0C = lire les 6 joints', 9, fg=MUTED).pack(side='right', padx=10)

        # --- Journal ---
        frame = tk.Frame(root, bg=PANEL)
        frame.pack(fill='both', expand=True, padx=20, pady=(0, 6))
        bar = tk.Frame(frame, bg=PANEL)
        bar.pack(fill='x', padx=12, pady=(8, 4))
        label(bar, 'JOURNAL DES ÉCHANGES', 11, True).pack(side='left')
        self.log_poll = tk.BooleanVar(value=False)
        tk.Checkbutton(bar, text='inclure la lecture périodique', variable=self.log_poll,
                       command=self.toggle_trace, bg=PANEL, fg=MUTED, activebackground=PANEL,
                       activeforeground=WHITE, selectcolor=BG, font=(FONT, 9)).pack(side='left', padx=12)
        btn(bar, 'Vider', self.clear).pack(side='right')
        btn(bar, 'Décoder la trame', self.decode_selected, '#265781').pack(side='right', padx=8)
        self.details = label(frame, 'Cliquer sur une ligne pour voir les octets ; « Décoder » affiche aussi les float32.',
                             9, fg=BLUE, anchor='w', justify='left')
        self.details.pack(side='bottom', fill='x', padx=13, pady=(4, 8))
        wrap = tk.Frame(frame, bg=PANEL)
        wrap.pack(fill='both', expand=True, padx=12)
        self.tree = ttk.Treeview(wrap, columns=('time', 'name', 'result'), show='headings',
                                 style='Lab.Treeview', height=4)
        for col, title, width in [('time', 'Heure', 80), ('name', 'Opération', 600), ('result', 'Résultat', 120)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col == 'name')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.show_selected)
        self.note = label(root, 'Une erreur robot ne renvoie pas d’exception Modbus : lire IR 120 après chaque commande.',
                          9, fg=MUTED, bg=BG, anchor='w')
        self.note.pack(fill='x', padx=20, pady=(0, 8))

        CommandWorker(self.cible, self.commands, self.updates, self.stop).start()
        PollWorker(self.cible, self.updates, self.poll_on, self.trace_poll, self.stop).start()
        self.tick()

    # ----- saisie -----
    def fill_joints(self, joints):
        for var, q in zip(self.jvars, joints):
            var.set(f'{round(math.degrees(q), 1) + 0:.1f}')

    def fill_pose(self, pose):
        for i, (var, v) in enumerate(zip(self.pvars, pose)):
            val = v * 1000 if i < 3 else math.degrees(v)
            var.set(f'{round(val, 1) + 0:.1f}')

    def copy_joints(self):
        if 'joints' in self.last:
            self.fill_joints(self.last['joints'])

    def copy_pose(self):
        if 'pose' in self.last:
            self.fill_pose(self.last['pose'])

    def read_fields(self, kind):
        try:
            if kind == 0:
                return [math.radians(float(v.get().replace(',', '.'))) for v in self.jvars]
            values = [float(v.get().replace(',', '.')) for v in self.pvars]
            return [v / 1000 for v in values[:3]] + [math.radians(v) for v in values[3:]]
        except ValueError:
            messagebox.showerror('Valeur', 'Les champs doivent contenir des nombres.')
            return None

    # ----- commandes -----
    def send(self, steps):
        self.commands.put(steps)

    def move(self, kind):
        values = self.read_fields(kind)
        if values is None:
            return
        regs = floats_to_regs(values)
        addr = 50 if kind == 0 else 62
        text = 'cible articulaire' if kind == 0 else 'cible en pose'
        self.send([(f'FC16 • HR {addr}–{addr + 11} = {text} (6 float32)',
                    lambda c: c.write_registers(addr, regs)),
                   (f'FC06 • HR 74 = {kind} → {MOVES[kind]}', lambda c: c.write_register(74, kind)),
                   ('FC05 • Coil 113 = 1 → lancer le mouvement', lambda c: c.write_coil(113, True)),
                   ('FC04 • Résultat de la commande (IR 120)', lambda c: c.read(4, 120, 1))])
        self.note.config(text=f'{MOVES[kind]} envoyé…', fg=ORANGE)

    def send_speed(self):
        try:
            value = int(self.speed.get())
        except ValueError:
            messagebox.showerror('Valeur', 'Vitesse entière attendue.')
            return
        self.send([(f'FC06 • HR 142 = {value} → vitesse du bras', lambda c: c.write_register(142, value)),
                   ('FC04 • Résultat de la commande (IR 120)', lambda c: c.read(4, 120, 1))])

    def send_blocking(self):
        on = self.blocking.get()
        self.send([(f'FC05 • Coil 118 = {int(on)} → mouvements {"bloquants" if on else "non bloquants"}',
                    lambda c: c.write_coil(118, on))])

    def send_raw(self):
        try:
            pdu = bytes.fromhex(self.raw.get().strip())
            if not pdu:
                raise ValueError('trame vide')
        except ValueError as exc:
            messagebox.showerror('Trame', f'Hexadécimal invalide : {exc}')
            return
        self.send([(f'PDU manuelle • {hx(pdu)}', lambda c: c.exchange_raw(pdu))])

    def toggle_trace(self):
        (self.trace_poll.set if self.log_poll.get() else self.trace_poll.clear)()

    # ----- journal -----
    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.rows.clear()

    def show_selected(self, _event=None):
        items = self.tree.selection()
        if items and items[0] in self.rows:
            req, resp = self.rows[items[0]]
            self.details.config(text=f' REQUÊTE : {req}\n RÉPONSE : {resp}')

    def decode_selected(self):
        items = self.tree.selection()
        if not items or items[0] not in self.rows:
            messagebox.showinfo('Décodage', 'Sélectionne d’abord une ligne dans le journal.')
            return
        request, response = self.rows[items[0]]
        popup = tk.Toplevel(self.root)
        popup.title('Décodeur Modbus TCP — trame Ned2')
        popup.geometry('760x680')
        popup.configure(bg=BG)
        label(popup, 'ANALYSE D’UNE TRANSACTION AVEC LE NED2', 16, True, BLUE, BG).pack(
            anchor='w', padx=20, pady=(16, 6))
        label(popup, 'Les réels Niryo sont des float32 sur 2 registres, mot de poids fort en premier.',
              10, fg=MUTED, bg=BG).pack(anchor='w', padx=20, pady=(0, 8))
        text = tk.Text(popup, bg=PANEL, fg=WHITE, relief='flat', font=('Courier', 11),
                       padx=14, pady=14, wrap='word')
        text.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        text.insert('1.0', decode_pair(request, response, floats=True))
        text.configure(state='disabled')

    # ----- affichage -----
    def show_poll(self, data):
        nums = regs_to_floats(data[(4, 50)])
        joints, pose = nums[:6], nums[6:12]
        self.last = {'joints': joints, 'pose': pose}
        for i, q in enumerate(joints):
            self.values[f'J{i + 1} °'].config(text=f'{round(math.degrees(q), 1) + 0:.1f}')
        for name, v in zip(self.pnames, pose):
            val = v * 1000 if 'mm' in name else math.degrees(v)
            self.values[name].config(text=f'{round(val, 1) + 0:.1f}')
        result, tool = data[(4, 120)]
        moving, _learning, _cal_needed, _cal, collision, blocking = data[(1, 113)]
        items = [('En mouvement (c113)', 'OUI' if moving else 'non', GREEN if moving else WHITE),
                 ('Pince fermée (c51)', 'OUI' if data[(1, 51)][0] else 'non', WHITE),
                 ('Collision (c117)', 'OUI' if collision else 'non', RED if collision else WHITE),
                 ('Commande (DI 51)', 'en cours' if data[(2, 50)][1] else '—', ORANGE if data[(2, 50)][1] else WHITE),
                 ('Résultat (IR 120)', RESULTS.get(result, str(result)), RED if result else GREEN),
                 ('DI1 carton', 'présent' if data[(2, 0)][0] else 'absent', GREEN if data[(2, 0)][0] else WHITE),
                 ('Outil (IR 121)', f'{tool} (Gripper 1)' if tool == 11 else str(tool), WHITE),
                 ('Vitesse (HR 142)', f'{data[(3, 142)][0]} %', WHITE),
                 ('Pièces (HR 401)', str(data[(3, 400)][1]), WHITE)]
        for name, text, color in items:
            self.values[name].config(text=text, fg=color)
        if self.blocking.get() != bool(blocking) and self.commands.empty():
            self.blocking.set(bool(blocking))

    def tick(self):
        try:
            for _ in range(200):
                try:
                    event = self.updates.get_nowait()
                except queue.Empty:
                    break
                kind = event[0]
                if kind == 'connection':
                    _, ok, text = event
                    self.connected.config(text=('● ' if ok is not False else '○ ') + text,
                                          fg={True: GREEN, False: RED}.get(ok, ORANGE))
                elif kind == 'poll':
                    self.show_poll(event[1])
                elif kind == 'trace':
                    _, stamp, text, req, resp, result = event
                    item = self.tree.insert('', 'end', values=(stamp, text, result))
                    self.rows[item] = (req, resp)
                    self.tree.see(item)
                    while len(self.tree.get_children()) > 300:
                        old = self.tree.get_children()[0]
                        self.tree.delete(old)
                        self.rows.pop(old, None)
                elif kind == 'result':
                    code = event[1]
                    if code == 0:
                        self.note.config(text='Commande exécutée : IR 120 = 0 (OK).', fg=GREEN)
                    else:
                        self.note.config(text=f'Commande refusée par le robot : IR 120 = {RESULTS.get(code, code)} '
                                              '(aucune exception Modbus n’est renvoyée).', fg=RED)
                elif kind == 'note':
                    self.note.config(text=event[1], fg=event[2])
        finally:
            if not self.stop.is_set():
                self.root.after(80, self.tick)

    def close(self):
        self.stop.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Pupitre Modbus TCP pour robot Niryo Ned2.')
    parser.add_argument('--host', default='127.0.0.1', help='Adresse du robot (virtuel ou réel)')
    parser.add_argument('--port', type=int, default=PORT_NED2)
    args = parser.parse_args()
    root = tk.Tk()
    RobotPanel(root, args.host, args.port)
    root.mainloop()


if __name__ == '__main__':
    main()
