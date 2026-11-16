"""Fenêtre du robot Ned2 virtuel (ouverte par le simulateur)."""
import math
import tkinter as tk

from bouton import BoutonPlat
from robot_ned2 import (BINS, BIN_HALF, BOX, BELT_Z, CONV_LEN, FINGER, PICK_X,
                        box_xyz, robot)

BG = '#101827'; PANEL = '#192638'; PANEL2 = '#223248'
WHITE = '#eef5ff'; MUTED = '#9cafc5'; GREEN = '#4bd6a0'
RED = '#ff7286'; BLUE = '#71b9ff'; ORANGE = '#ffbd6c'
FONT = 'Arial'
ARM = '#c9d6e3'; ARM_DARK = '#6f8aa3'; BOX_FILL = '#d99a5e'; BOX_LINE = '#84532f'
RESULTS = {0: 'OK', 1: 'erreur Modbus', 2: 'erreur robot'}


def label(parent, text, size=10, bold=False, fg=WHITE, bg=PANEL, **kw):
    return tk.Label(parent, text=text, bg=bg, fg=fg,
                    font=(FONT, size, 'bold' if bold else 'normal'), **kw)


def btn(parent, text, command, bg=PANEL2):
    return BoutonPlat(parent, text, command, bg=bg, fg=WHITE,
                      font=(FONT, 10, 'bold'), padx=11, pady=8)


class RobotWindow:
    def __init__(self, root, machine, host, port):
        self.machine = machine
        self.win = tk.Toplevel(root)
        self.win.title('MODBUS LAB — Robot Niryo Ned2 virtuel (serveur)')
        self.win.geometry('900x700')
        self.win.minsize(820, 640)
        self.win.configure(bg=BG)
        self.win.protocol('WM_DELETE_WINDOW', self.win.withdraw)

        head = tk.Frame(self.win, bg=BG)
        head.pack(fill='x', padx=18, pady=(14, 8))
        label(head, 'ROBOT NED2', 20, True, BLUE, BG).pack(side='left')
        label(head, '   table Modbus du firmware Niryo', 12, fg=MUTED, bg=BG).pack(side='left', pady=5)
        label(head, f'SERVEUR TCP : {host}:{port}', 10, True, GREEN, BG).pack(side='right', pady=6)

        views = tk.Frame(self.win, bg=BG)
        views.pack(fill='x', padx=18)
        left = tk.Frame(views, bg=PANEL)
        left.pack(side='left', fill='both', expand=True, padx=(0, 10))
        label(left, 'VUE DE DESSUS — cellule', 11, True).pack(anchor='w', padx=12, pady=(10, 4))
        self.top = tk.Canvas(left, height=300, bg='#0f1c2c', highlightthickness=0)
        self.top.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        right = tk.Frame(views, bg=PANEL)
        right.pack(side='left', fill='both', expand=True)
        label(right, 'VUE DE PROFIL — plan du bras (J1)', 11, True).pack(anchor='w', padx=12, pady=(10, 4))
        self.side = tk.Canvas(right, height=300, bg='#0f1c2c', highlightthickness=0)
        self.side.pack(fill='both', expand=True, padx=12, pady=(0, 12))

        info = tk.Frame(self.win, bg=BG)
        info.pack(fill='x', padx=18, pady=10)
        self.values = {}
        cards = [('ARTICULATIONS (°)', ['J1', 'J2', 'J3', 'J4', 'J5', 'J6']),
                 ('POSE OUTIL', ['x (mm)', 'y (mm)', 'z (mm)', 'roll (°)', 'pitch (°)', 'yaw (°)']),
                 ('ÉTAT', ['Mouvement', 'Pince', 'Collision', 'Commande', 'Dernier résultat', 'DI1 carton'])]
        for title, names in cards:
            card = tk.Frame(info, bg=PANEL)
            card.pack(side='left', fill='both', expand=True, padx=(0, 10))
            label(card, title, 9, True, MUTED).pack(anchor='w', padx=12, pady=(9, 4))
            for name in names:
                row = tk.Frame(card, bg=PANEL)
                row.pack(fill='x', padx=12, pady=0)
                label(row, name, 9, fg=MUTED).pack(side='left')
                value = label(row, '—', 10, True)
                value.pack(side='right')
                self.values[name] = value
            tk.Frame(card, bg=PANEL, height=8).pack()

        ctrl = tk.Frame(self.win, bg=PANEL)
        ctrl.pack(fill='x', padx=18, pady=(0, 10))
        line1 = tk.Frame(ctrl, bg=PANEL)
        line1.pack(fill='x', padx=8, pady=(9, 4))
        label(line1, 'PROGRAMME EMBARQUÉ', 10, True, BLUE).pack(side='left', padx=(4, 10))
        btn(line1, '▶ Lancer', robot.start_program, '#126648').pack(side='left', padx=3)
        btn(line1, '■ Arrêter', robot.stop_program, '#8b3848').pack(side='left', padx=3)
        self.program = label(line1, '', 10, fg=MUTED)
        self.program.pack(side='left', padx=12)
        line2 = tk.Frame(ctrl, bg=PANEL)
        line2.pack(fill='x', padx=8, pady=(4, 10))
        self.cell = tk.BooleanVar(value=machine.robot_cell)
        tk.Checkbutton(line2, text='Poste robot : cartons arrêtés en bout de tapis',
                       variable=self.cell, command=self.toggle_cell, bg=PANEL, fg=WHITE,
                       activebackground=PANEL, activeforeground=WHITE, selectcolor=BG,
                       font=(FONT, 10)).pack(side='left', padx=4)
        btn(line2, 'Simuler une collision', robot.simulate_collision, '#815025').pack(side='left', padx=8)
        btn(line2, 'Vider les bacs', self.empty_bins).pack(side='left', padx=3)
        self.bins = label(line2, '', 10, True, ORANGE)
        self.bins.pack(side='right', padx=8)
        self.message = label(self.win, '', 10, fg=ORANGE, bg=BG, anchor='w')
        self.message.pack(fill='x', padx=20, pady=(0, 8))

    def toggle_cell(self):
        self.machine.set_robot_cell(self.cell.get())

    def empty_bins(self):
        with robot.lock:
            robot.bins = {'A': 0, 'B': 0, 'sol': 0}

    # ----- dessin -----
    def draw_top(self, snap, boxes):
        c = self.top
        c.delete('all')
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 240)
        scale = min(w / 1.0, h / 0.46)
        ox, oy = w * 0.6, h - 0.13 * scale       # base du robot

        def pt(x, y):          # X du robot vers le haut, Y vers la gauche
            return ox - y * scale, oy - x * scale

        # Bacs
        for name, (bx, by) in BINS.items():
            x0, y0 = pt(bx + BIN_HALF, by + BIN_HALF)
            x1, y1 = pt(bx - BIN_HALF, by - BIN_HALF)
            c.create_rectangle(x0, y0, x1, y1, outline=ORANGE, width=2, dash=(5, 3))
            c.create_text((x0 + x1) / 2, y1 + 11, text=f'BAC {name}', fill=ORANGE,
                          font=(FONT, 9, 'bold'))
        # Convoyeur
        x0, y0 = pt(PICK_X + 0.045, CONV_LEN + 0.1)
        x1, y1 = pt(PICK_X - 0.045, -0.03)
        c.create_rectangle(x0, y0, x1, y1, fill='#273a4e', outline='#52738c', width=2)
        c.create_text(max(x0, 0) + 8, y0 - 9, text='CONVOYEUR →', fill=MUTED, anchor='w',
                      font=(FONT, 9, 'bold'))
        sx, sy = pt(PICK_X + 0.06, 0.0)
        c.create_oval(sx - 5, sy - 5, sx + 5, sy + 5,
                      fill=GREEN if snap['di'][0] else '#547086', outline='')
        c.create_text(sx, sy - 11, text='S2 → DI1', fill=MUTED, font=(FONT, 8))
        half = BOX / 2 * scale
        for pos in boxes:
            bx, by, _ = box_xyz(pos)
            if by > CONV_LEN + 0.08:
                continue
            u, v = pt(bx, by)
            c.create_rectangle(u - half, v - half, u + half, v + half,
                               fill=BOX_FILL, outline=BOX_LINE, width=2)
        # Bras (projection sur la table)
        pts = [pt(x, y) for x, y, _ in snap['points']]
        u, v = pts[0]
        c.create_oval(u - 0.06 * scale, v - 0.06 * scale, u + 0.06 * scale, v + 0.06 * scale,
                      fill='#2c4055', outline=ARM_DARK, width=2)
        c.create_line(*[k for p in pts for k in p], fill=ARM, width=7, capstyle='round',
                      joinstyle='round')
        tx, ty, _ = snap['fingertip']
        u, v = pt(tx, ty)
        if snap['held']:
            c.create_rectangle(u - half, v - half, u + half, v + half,
                               fill=BOX_FILL, outline=BOX_LINE, width=2)
        c.create_oval(u - 4, v - 4, u + 4, v + 4, fill=GREEN if snap['gripper_closed'] else BLUE,
                      outline='')
        c.create_text(8, 12, text='X ↑   Y ←   (repère du robot)', fill=MUTED,
                      anchor='w', font=(FONT, 8))

    def draw_side(self, snap, boxes):
        c = self.side
        c.delete('all')
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 240)
        scale = min(w / 0.78, h / 0.58)
        ox, oy = w * 0.2, h - 24
        q1 = snap['joints'][0]
        cos1, sin1 = math.cos(q1), math.sin(q1)

        def pt(x, y, z):        # projection sur le plan vertical orienté par J1
            return ox + (x * cos1 + y * sin1) * scale, oy - z * scale

        c.create_line(0, oy, w, oy, fill='#3a5068', width=2)
        # Objets situés dans le plan du bras (à ±25°)
        for name, (bx, by) in BINS.items():
            if abs((math.atan2(by, bx) - q1 + math.pi) % (2 * math.pi) - math.pi) < 0.45:
                d = math.hypot(bx, by)
                u0, u1 = ox + (d - BIN_HALF) * scale, ox + (d + BIN_HALF) * scale
                c.create_line(u0, oy - 0.05 * scale, u0, oy, u1, oy, u1, oy - 0.05 * scale,
                              fill=ORANGE, width=3)
                c.create_text((u0 + u1) / 2, oy + 12, text=f'BAC {name}', fill=ORANGE,
                              font=(FONT, 9, 'bold'))
        if abs(q1) < 0.45:
            d = PICK_X / max(cos1, 0.2)
            u0, u1 = ox + (d - 0.045) * scale, ox + (d + 0.045) * scale
            c.create_rectangle(u0, oy - BELT_Z * scale, u1, oy, fill='#273a4e', outline='#52738c')
            c.create_text((u0 + u1) / 2, oy + 12, text='TAPIS', fill=MUTED, font=(FONT, 9, 'bold'))
            for pos in boxes:
                bx, by, bz = box_xyz(pos)
                if abs(math.atan2(by, bx) - q1) < 0.06:
                    u, v = pt(bx, by, bz)
                    half = BOX / 2 * scale
                    c.create_rectangle(u - half, v - half, u + half, v + half,
                                       fill=BOX_FILL, outline=BOX_LINE, width=2)
        # Socle et bras
        c.create_rectangle(ox - 0.06 * scale, oy - 0.09 * scale, ox + 0.06 * scale, oy,
                           fill='#2c4055', outline=ARM_DARK, width=2)
        pts = [pt(*p) for p in snap['points']]
        c.create_line(*[k for p in pts for k in p], fill=ARM, width=11, capstyle='round',
                      joinstyle='round')
        for u, v in pts[1:-1]:
            c.create_oval(u - 5, v - 5, u + 5, v + 5, fill=ARM_DARK, outline='')
        # Pince : deux doigts le long de l'axe X outil
        tool = snap['points'][-1]
        ax, ay, az = snap['axes']
        side_axis = max((ay, az), key=lambda a: abs(a[0] * cos1 + a[1] * sin1) + abs(a[2]))
        spread = 0.022 - 0.012 * snap['gripper']
        for sign in (-1, 1):
            base = [tool[i] + sign * spread * side_axis[i] for i in range(3)]
            tip = [base[i] + FINGER * ax[i] for i in range(3)]
            c.create_line(*pt(*base), *pt(*tip), fill=GREEN if snap['gripper_closed'] else BLUE,
                          width=4, capstyle='round')
        if snap['held']:
            u, v = pt(*snap['fingertip'])
            half = BOX / 2 * scale
            c.create_rectangle(u - half, v - half + 4, u + half, v + half + 4,
                               fill=BOX_FILL, outline=BOX_LINE, width=2)
        c.create_text(8, 12, text=f'J1 = {round(math.degrees(q1)) + 0}°', fill=MUTED, anchor='w',
                      font=(FONT, 9, 'bold'))

    def refresh(self):
        if not self.win.winfo_viewable():
            return
        snap = robot.snapshot()
        boxes = [p for _, p in self.machine.box_positions()]
        self.draw_top(snap, boxes)
        self.draw_side(snap, boxes)
        for i, q in enumerate(snap['joints']):
            self.values[f'J{i + 1}'].config(text=f'{round(math.degrees(q), 1) + 0:7.1f}')
        x, y, z, r, p, yaw = snap['pose']
        for name, val in [('x (mm)', x * 1000), ('y (mm)', y * 1000), ('z (mm)', z * 1000),
                          ('roll (°)', math.degrees(r)), ('pitch (°)', math.degrees(p)),
                          ('yaw (°)', math.degrees(yaw))]:
            self.values[name].config(text=f'{round(val, 1) + 0:7.1f}')
        states = [('Mouvement', 'EN COURS' if snap['moving'] else 'arrêté', GREEN if snap['moving'] else WHITE),
                  ('Pince', 'fermée' if snap['gripper_closed'] else 'ouverte', WHITE),
                  ('Collision', 'OUI' if snap['collision'] else 'non', RED if snap['collision'] else WHITE),
                  ('Commande', 'en cours' if snap['executing'] else '—', WHITE),
                  ('Dernier résultat', f"{snap['last_result']} · {RESULTS.get(snap['last_result'], '?')}",
                   RED if snap['last_result'] else WHITE),
                  ('DI1 carton', 'présent' if snap['di'][0] else 'absent', GREEN if snap['di'][0] else WHITE)]
        for name, text, color in states:
            self.values[name].config(text=text, fg=color)
        bins = snap['bins']
        self.bins.config(text=f"Bac A : {bins['A']}   Bac B : {bins['B']}   Hors bacs : {bins['sol']}")
        text = snap['program_text']
        if snap['pause'] and snap['program']:
            text += '  (coil 200 = pause)'
        self.program.config(text=text, fg=GREEN if snap['program'] else MUTED)
        self.message.config(text=snap['message'])
        if self.cell.get() != self.machine.robot_cell:
            self.cell.set(self.machine.robot_cell)
