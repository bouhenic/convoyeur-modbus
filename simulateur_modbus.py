#!/usr/bin/env python3
"""Simulateur de convoyeur et serveur Modbus TCP — interface Tkinter."""
import argparse
import time
import tkinter as tk
from tkinter import ttk, messagebox
from modbus_core import local_ipv4, machine, start_server
from bouton import BoutonPlat
from robot_ned2 import PORT_NED2, describe_robot, process_pdu_robot, robot

BG = '#101827'
PANEL = '#192638'
PANEL2 = '#223248'
WHITE = '#eef5ff'
MUTED = '#9cafc5'
GREEN = '#4bd6a0'
RED = '#ff7286'
BLUE = '#71b9ff'
ORANGE = '#ffbd6c'
FONT = 'Arial'


def label(parent, text, size=11, bold=False, fg=WHITE, bg=BG, **kwargs):
    return tk.Label(parent, text=text, bg=bg, fg=fg,
                    font=(FONT, size, 'bold' if bold else 'normal'), **kwargs)


def btn(parent, text, command, fg=WHITE, bg=PANEL2, width=None):
    return BoutonPlat(parent, text, command, bg=bg, fg=fg,
                      font=(FONT, 10, 'bold'), padx=13, pady=10, width=width)


def start_robot_server(host, port):
    """Serveur du Ned2 : comme pymodbus sur le robot, tout Unit ID est accepté
    et une connexion inactive n'est pas coupée."""
    robot.conveyor = machine
    return start_server(host, port, process=process_pdu_robot, describe=describe_robot,
                        accept_unit=lambda unit: True, idle_timeout=None, clients=set())


class SimGui:
    def __init__(self, root, server, host, port, robot_server=None):
        self.root, self.server, self.robot_server = root, server, robot_server
        self.last_tick = time.monotonic()
        self.last_event_id = 0
        self.visible_events = {}
        root.title('MODBUS LAB — Simulateur industriel (serveur)')
        root.geometry('1150x880')
        root.minsize(970, 780)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Lab.Treeview', background=PANEL, fieldbackground=PANEL,
                        foreground=WHITE, rowheight=24, borderwidth=0,
                        font=(FONT, 10))
        style.configure('Lab.Treeview.Heading', background=PANEL2, foreground=WHITE,
                        relief='flat', font=(FONT, 10, 'bold'))
        style.map('Lab.Treeview', background=[('selected', '#2c5e86')])

        heading = tk.Frame(root, bg=BG)
        heading.pack(fill='x', padx=22, pady=(16, 8))
        label(heading, 'MODBUS LAB', 24, True, BLUE).pack(side='left')
        label(heading, '   Convoyeur industriel virtuel', 14, fg=MUTED).pack(side='left', pady=7)
        iptext = f'127.0.0.1:{port}' if host == '127.0.0.1' else f'{local_ipv4()}:{port}'
        label(heading, f'SERVEUR TCP : {iptext}', 10, True, GREEN).pack(side='right', pady=8)

        body = tk.Frame(root, bg=BG)
        body.pack(fill='both', expand=False, padx=22, pady=(0, 10))
        left = tk.Frame(body, bg=PANEL)
        left.pack(side='left', fill='both', expand=True, padx=(0, 12))
        right = tk.Frame(body, bg=PANEL, width=360)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)

        top = tk.Frame(left, bg=PANEL)
        top.pack(fill='x', padx=14, pady=(13, 4))
        label(top, 'LIGNE DE PRODUCTION', 13, True, bg=PANEL).pack(side='left')
        self.status = label(top, 'ARRÊT', 10, True, RED, PANEL)
        self.status.pack(side='right')
        self.canvas = tk.Canvas(left, height=180, bg='#0f1c2c', highlightthickness=0)
        self.canvas.pack(fill='x', padx=14, pady=(2, 8))

        indicators = tk.Frame(left, bg=PANEL)
        indicators.pack(fill='x', padx=15, pady=(0, 10))
        self.labels = {}
        for key, title in [('count', 'CARTONS PRODUITS'), ('speed', 'VITESSE'),
                           ('entry', 'CAPTEUR ENTRÉE'), ('exit', 'CAPTEUR SORTIE')]:
            card = tk.Frame(indicators, bg=PANEL2)
            card.pack(side='left', fill='both', expand=True, padx=4)
            label(card, title, 8, True, MUTED, PANEL2).pack(pady=(10, 4))
            v = label(card, '–', 18, True, WHITE, PANEL2)
            v.pack(pady=(0, 10))
            self.labels[key] = v

        label(left, 'COMMANDES LOCALES — pour tester sans client Modbus', 10, True,
              MUTED, PANEL).pack(anchor='w', padx=18, pady=(2, 5))
        commands = tk.Frame(left, bg=PANEL)
        commands.pack(fill='x', padx=12, pady=(0, 13))
        btn(commands, '▶ MARCHE', lambda: machine.set_run(True), bg='#126648').pack(side='left', padx=4)
        btn(commands, '■ ARRÊT', lambda: machine.set_run(False), bg='#8b3848').pack(side='left', padx=4)
        btn(commands, 'Remise à zéro', machine.reset_count).pack(side='left', padx=4)

        label(right, 'TABLE DES REGISTRES', 13, True, WHITE, PANEL).pack(anchor='w', padx=15, pady=(14, 5))
        label(right, 'Offsets transmis dans la trame (base 0)', 9, fg=MUTED,
              bg=PANEL).pack(anchor='w', padx=15, pady=(0, 9))
        self.reg_labels = []
        rows = [('Coil 0', 'Marche demandée'), ('Coil 1', 'Acquit (impulsion)'),
                ('Coil 2', 'RAZ (impulsion)'), ('HR 0', 'Vitesse (%)'),
                ('HR 1', 'Objectif cartons'), ('IR 0', 'Cartons produits'),
                ('IR 1', 'Moteur réel'), ('IR 2', 'Capteur entrée'),
                ('IR 3', 'Capteur sortie'), ('IR 4', 'Code défaut'),
                ('IR 5', 'Cartons sur bande'), ('IR 6', 'État machine')]
        for name, description in rows:
            row = tk.Frame(right, bg=PANEL)
            row.pack(fill='x', padx=15, pady=1)
            label(row, name, 10, True, BLUE, PANEL, width=8, anchor='w').pack(side='left')
            label(row, description, 9, fg=MUTED, bg=PANEL).pack(side='left', fill='x', expand=True)
            value = label(row, '—', 10, True, WHITE, PANEL, width=5, anchor='e')
            value.pack(side='right')
            self.reg_labels.append(value)

        extras = tk.Frame(root, bg=BG)
        extras.pack(fill='x', padx=22, pady=(0, 10))
        local = tk.Frame(extras, bg=PANEL)
        local.pack(side='left', fill='x', expand=True, padx=(0, 12))
        label(local, 'INJECTION DE DÉFAUTS — simulation uniquement', 10, True,
              ORANGE, PANEL).pack(anchor='w', padx=14, pady=(9, 6))
        row = tk.Frame(local, bg=PANEL)
        row.pack(anchor='w', padx=10, pady=(0, 10))
        btn(row, 'Créer un bourrage', machine.inject_jam, bg='#815025').pack(side='left', padx=4)
        btn(row, 'Libérer le bourrage', machine.release_jam).pack(side='left', padx=4)
        btn(row, 'Acquitter', machine.acknowledge, bg='#2d645c').pack(side='left', padx=4)
        e = tk.Frame(extras, bg=PANEL, width=360)
        e.pack(side='right', fill='y')
        e.pack_propagate(False)
        label(e, 'ARRÊT D’URGENCE VIRTUEL', 10, True, RED, PANEL).pack(anchor='w', padx=13, pady=(9, 6))
        sub = tk.Frame(e, bg=PANEL)
        sub.pack(anchor='w', padx=9, pady=(0, 9))
        btn(sub, 'Déclencher', machine.press_estop, bg='#8b3848').pack(side='left', padx=4)
        btn(sub, 'Déverrouiller', machine.release_estop).pack(side='left', padx=4)

        setting = tk.Frame(root, bg=PANEL)
        setting.pack(fill='x', padx=22, pady=(0, 10))
        label(setting, 'PARAMÈTRES LOCAUX', 10, True, MUTED, PANEL).pack(side='left', padx=12)
        label(setting, 'Vitesse (%)', 10, bg=PANEL).pack(side='left', padx=(12, 5))
        self.speed_var = tk.StringVar(value='50')
        tk.Spinbox(setting, from_=1, to=100, width=5, textvariable=self.speed_var,
                   bg=PANEL2, fg=WHITE, buttonbackground=PANEL2, insertbackground=WHITE,
                   relief='flat').pack(side='left')
        label(setting, 'Objectif (0 = continu)', 10, bg=PANEL).pack(side='left', padx=(18, 5))
        self.target_var = tk.StringVar(value='0')
        self.last_seen_speed, self.last_seen_target = 50, 0
        tk.Spinbox(setting, from_=0, to=5000, width=6, textvariable=self.target_var,
                   bg=PANEL2, fg=WHITE, buttonbackground=PANEL2, insertbackground=WHITE,
                   relief='flat').pack(side='left')
        btn(setting, 'Appliquer', self.apply_settings, bg='#255a86').pack(side='left', padx=16, pady=8)
        self.network = label(setting, 'Clients : 0', 10, fg=GREEN, bg=PANEL)
        self.network.pack(side='right', padx=12)

        logframe = tk.Frame(root, bg=PANEL)
        logframe.pack(fill='both', expand=True, padx=22, pady=(0, 18))
        bar = tk.Frame(logframe, bg=PANEL)
        bar.pack(fill='x', padx=12, pady=(8, 5))
        label(bar, 'TRAMES MODBUS TCP', 12, True, WHITE, PANEL).pack(side='left')
        btn(bar, 'Effacer la vue', self.clear_log).pack(side='right')
        self.show_ports = {}
        shown = [(port, 'Convoyeur')] + ([(robot_server.server_address[1], 'Robot')]
                                          if robot_server is not None else [])
        for p, name in shown:
            var = tk.BooleanVar(value=True)
            self.show_ports[f':{p}'] = var
            tk.Checkbutton(bar, text=f'{name} :{p}', variable=var, bg=PANEL, fg=MUTED,
                           activebackground=PANEL, activeforeground=WHITE, selectcolor=BG,
                           font=(FONT, 9)).pack(side='left', padx=(14, 0))
        # Ligne d'aide placée en bas avant le tableau : elle reste visible
        # et c'est le tableau qui rétrécit si la fenêtre manque de hauteur.
        self.detail = label(logframe, 'Sélectionne une transaction pour voir la requête et la réponse hexadécimales.',
                            9, fg=BLUE, bg=PANEL, anchor='w', justify='left')
        self.detail.pack(side='bottom', fill='x', padx=14, pady=(5, 10))
        logbody = tk.Frame(logframe, bg=PANEL)
        logbody.pack(fill='both', expand=True, padx=12)
        self.tree = ttk.Treeview(logbody, style='Lab.Treeview', show='headings', height=5,
                                 columns=('time', 'peer', 'function', 'info'))
        for c, title, w in [('time', 'Heure', 78), ('peer', 'Client → port', 150),
                            ('function', 'FC', 58), ('info', 'Explication de la requête', 650)]:
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, stretch=c == 'info')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(logbody, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.config(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.show_selected)
        self.robot_window = None
        if robot_server is not None:
            from robot_gui import RobotWindow
            self.robot_window = RobotWindow(root, machine, iptext.rsplit(':', 1)[0],
                                            robot_server.server_address[1])
            btn(commands, 'Fenêtre robot', self.robot_window.win.deiconify).pack(side='right', padx=4)
        self.update()

    def apply_settings(self):
        try:
            speed, target = int(self.speed_var.get()), int(self.target_var.get())
        except ValueError:
            messagebox.showerror('Paramètres', 'Entre des nombres entiers.')
            return
        if not 1 <= speed <= 100 or not 0 <= target <= 5000:
            messagebox.showerror('Paramètres', 'Vitesse : 1–100 ; objectif : 0–5000.')
            return
        machine.set_speed(speed)
        machine.set_target(target)

    def clear_log(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.visible_events.clear()
        self.detail.config(text='Journal visuel effacé ; les prochaines trames apparaîtront ici.')

    def show_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        event = self.visible_events.get(selected[0])
        if event:
            self.detail.config(text=f' REQUÊTE : {event.request}\n RÉPONSE : {event.response}')

    def draw(self, snap):
        c = self.canvas
        c.delete('all')
        width = max(550, c.winfo_width())
        x0, x1 = 46, width - 54
        y = 104
        c.create_text(x0, 24, text='ENTRÉE · S1', fill=MUTED, anchor='w', font=(FONT, 10, 'bold'))
        c.create_text(x1, 24, text='SORTIE · S2', fill=MUTED, anchor='e', font=(FONT, 10, 'bold'))
        # Rouleaux et tapis roulant
        c.create_rectangle(x0 - 13, y + 6, x1 + 23, y + 42, fill='#273a4e', outline='#52738c', width=2)
        for x in range(x0, x1 + 1, 40):
            c.create_oval(x - 9, y + 47, x + 9, y + 65, fill='#49647a', outline='#7395ac')
        c.create_line(x0 - 9, y + 9, x1 + 19, y + 9, fill=GREEN if snap['running'] else '#6a7e94', width=3)
        for i, pos in enumerate(snap['boxes']):
            x = x0 + pos * (x1 - x0)
            c.create_rectangle(x, y - 38, x + 42, y + 6, fill='#d99a5e', outline='#84532f', width=2)
            c.create_line(x + 22, y - 36, x + 22, y + 5, fill='#f7c998', width=2)
            c.create_line(x + 4, y - 17, x + 38, y - 17, fill='#f7c998')
        sensor = snap['inputs']
        for pos, idx, name in [(x0 + 22, 2, 'S1'), (x1 + 1, 3, 'S2')]:
            active = sensor[idx]
            color = GREEN if active else '#547086'
            c.create_oval(pos - 9, y - 67, pos + 9, y - 49, fill=color, outline='')
            c.create_line(pos, y - 49, pos, y - 5, fill=color, dash=(4, 5), width=2)
        if snap['inputs'][4]:
            c.create_text(x1, y + 66, text='⚠ DÉFAUT ACTIF', anchor='e', fill=RED,
                          font=(FONT, 11, 'bold'))

    def update(self):
        now = time.monotonic()
        machine.advance(now - self.last_tick)
        robot.advance(now - self.last_tick)
        self.last_tick = now
        if self.robot_window is not None:
            self.robot_window.refresh()
        snap = machine.snapshot()
        self.draw(snap)
        states = {0: ('ARRÊT', MUTED), 1: ('EN MARCHE', GREEN),
                  2: ('DÉFAUT — ACQUITTEMENT REQUIS', RED),
                  3: ('OBJECTIF ATTEINT', ORANGE)}
        status, color = states[snap['inputs'][6]]
        self.status.config(text=status, fg=color)
        for key, value in [('count', str(snap['count'])),
                           ('speed', f"{snap['speed']} %"),
                           ('entry', '● ACTIF' if snap['inputs'][2] else '○ LIBRE'),
                           ('exit', '● ACTIF' if snap['inputs'][3] else '○ LIBRE')]:
            self.labels[key].config(text=value,
                                    fg=GREEN if 'ACTIF' in value else WHITE)
        values = snap['coils'] + snap['holding'] + snap['inputs']
        for widget, value in zip(self.reg_labels, values):
            widget.config(text=str(value))
        # Mettre à jour les champs seulement s'ils ne contiennent pas
        # une modification locale en cours de saisie.
        if self.speed_var.get() == str(self.last_seen_speed):
            self.speed_var.set(str(snap['speed']))
        if self.target_var.get() == str(self.last_seen_target):
            self.target_var.set(str(snap['target']))
        self.last_seen_speed, self.last_seen_target = snap['speed'], snap['target']
        self.network.config(text=f"Clients : {snap['clients']}")
        new_events = machine.logs_after(self.last_event_id)
        for event_id, event in new_events:
            self.last_event_id = event_id
            port = event.peer.rsplit(' ', 1)[-1]
            if port in self.show_ports and not self.show_ports[port].get():
                continue
            item = self.tree.insert('', 'end', values=(event.stamp, event.peer,
                            event.action, event.explanation))
            self.visible_events[item] = event
        if new_events and self.tree.get_children():
            self.tree.see(self.tree.get_children()[-1])
        while len(self.tree.get_children()) > 200:
            old = self.tree.get_children()[0]
            self.visible_events.pop(old, None)
            self.tree.delete(old)
        self.root.after(60, self.update)

    def close(self):
        for srv in (self.server, self.robot_server):
            if srv is not None:
                srv.shutdown()
                srv.server_close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Serveur Modbus TCP et convoyeur virtuel.')
    parser.add_argument('--host', default='127.0.0.1', help='127.0.0.1 (PC seul) ou 0.0.0.0 (ESP32, LAN privé)')
    parser.add_argument('--port', type=int, default=1502)
    parser.add_argument('--robot-port', type=int, default=PORT_NED2,
                        help='Port du robot Ned2 virtuel (5020 comme le vrai robot)')
    parser.add_argument('--sans-robot', action='store_true', help='Ne pas simuler le robot Ned2')
    parser.add_argument('--headless', action='store_true', help='Lancer sans interface graphique')
    args = parser.parse_args()
    try:
        server = start_server(args.host, args.port)
    except OSError as exc:
        raise SystemExit(f'Impossible de démarrer Modbus TCP sur {args.host}:{args.port} : {exc}')
    print(f'Serveur Modbus TCP actif : {args.host}:{args.port} (Unit ID 1)', flush=True)
    robot_server = None
    if not args.sans_robot:
        try:
            robot_server = start_robot_server(args.host, args.robot_port)
            print(f'Robot Ned2 virtuel : {args.host}:{args.robot_port} (table Modbus Niryo)', flush=True)
        except OSError as exc:
            print(f'Robot Ned2 non démarré sur le port {args.robot_port} : {exc}', flush=True)
    print('Pour tester sur ce PC : python pupitre_pc.py  /  python pupitre_robot.py', flush=True)
    if args.host != '127.0.0.1':
        ip = local_ipv4()
        print(f'Depuis un autre PC : python pupitre_pc.py --host {ip}  /  '
              f'python pupitre_robot.py --host {ip}', flush=True)
    try:
        if args.headless:
            last, last_id = time.monotonic(), 0
            while True:
                time.sleep(.05)
                now = time.monotonic()
                machine.advance(now - last)
                robot.advance(now - last)
                last = now
                for event_id, event in machine.logs_after(last_id):
                    print(f'{event.stamp} [{event.peer}] {event.explanation} | {event.request} -> {event.response}', flush=True)
                    last_id = event_id
        else:
            root = tk.Tk()
            SimGui(root, server, args.host, args.port, robot_server)
            root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        for srv in (server, robot_server):
            if srv is not None:
                srv.shutdown()
                srv.server_close()


if __name__ == '__main__':
    main()
