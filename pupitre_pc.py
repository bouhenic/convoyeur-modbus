#!/usr/bin/env python3
"""Pupitre de commande PC : client Modbus TCP indépendant du simulateur.
Utilise 127.0.0.1:1502 par défaut (simulateur sur le même ordinateur).
Simulateur sur une autre machine : --host <IP>, ou champ « Serveur » de l'en-tête.
"""
import argparse
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from modbus_core import ModbusTcpClient, ModbusError, hx
from decodeur import decode_pair
from bouton import BoutonPlat
from cible import BarreServeur, Cible, message_erreur

BG = '#101827'; PANEL = '#192638'; PANEL2 = '#223248'
WHITE = '#eef5ff'; MUTED = '#9cafc5'; GREEN = '#4bd6a0'
RED = '#ff7286'; BLUE = '#71b9ff'; ORANGE = '#ffbd6c'
FONT = 'Arial'


def label(p, text, size=11, bold=False, fg=WHITE, bg=BG, **kw):
    return tk.Label(p, text=text, bg=bg, fg=fg,
                    font=(FONT, size, 'bold' if bold else 'normal'), **kw)


def btn(p, title, command, bg=PANEL2):
    return BoutonPlat(p, title, command, bg=bg, fg=WHITE,
                      font=(FONT, 11, 'bold'), padx=17, pady=11)


class Worker(threading.Thread):
    def __init__(self, cible, commands, updates, poll_enabled, stop):
        super().__init__(daemon=True)
        self.cible = cible
        self.commands, self.updates = commands, updates
        self.poll_enabled, self.stop = poll_enabled, stop

    def transaction(self, client, op, addr=0, val=0, label_text='', auto=False):
        request, response = b'', b''
        try:
            if op == 'read':
                values, request, response = client.read(val[0], addr, val[1])
                self.updates.put(('values', val[0], addr, values))
            elif op == 'coil':
                _, request, response = client.write_coil(addr, val)
            elif op == 'register':
                _, request, response = client.write_register(addr, val)
            elif op == 'raw':
                _, request, response = client.exchange_raw(val)
            self.updates.put(('trace', time.strftime('%H:%M:%S'), label_text,
                              hx(request), hx(response), False, auto))
            if op == 'raw':
                self.updates.put(('raw', hx(request), hx(response), ''))
            return True
        except ModbusError as exc:
            self.updates.put(('trace', time.strftime('%H:%M:%S'), label_text,
                              hx(exc.request), hx(exc.response), True, auto))
            if op == 'raw':
                self.updates.put(('raw', hx(exc.request), hx(exc.response), str(exc)))
            self.updates.put(('note', f'{label_text} → {exc}'))
            return True   # l'exception Modbus ne coupe pas la connexion

    def run(self):
        client = ModbusTcpClient()
        vue = -1
        last_poll = 0
        last_error = ''
        while not self.stop.is_set():
            vue, changee = self.cible.suivre(client, vue)
            if changee:
                last_error = ''
                self.updates.put(('connection', None, f'Connexion à {client.host}:{client.port}…'))
            if client.sock is None:
                try:
                    client.connect()
                    self.updates.put(('connection', True, f'Connecté à {client.host}:{client.port}'))
                    last_error = ''
                except (OSError, ValueError) as exc:
                    err = message_erreur(exc)
                    if err != last_error:
                        self.updates.put(('connection', False, f'Échec : {err}'))
                        last_error = err
                    self.stop.wait(1.0)
                    continue
            try:
                # Traiter les ordres utilisateur avant toute lecture périodique.
                for _ in range(8):
                    try:
                        cmd = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    op, addr, value, description = cmd
                    self.transaction(client, op, addr, value, description)
                if self.poll_enabled.is_set() and time.monotonic() - last_poll >= .9:
                    last_poll = time.monotonic()
                    for fc, addr, n, name in [(1, 0, 3, 'FC01 • Coils'),
                                               (2, 0, 2, 'FC02 • Entrées TOR'),
                                               (3, 0, 2, 'FC03 • Paramètres'),
                                               (4, 0, 7, 'FC04 • Capteurs / état')]:
                        self.transaction(client, 'read', addr, (fc, n), name, auto=True)
                if client.sock is None:
                    raise ConnectionError('Connexion perdue')
            except (OSError, ConnectionError, ValueError) as exc:
                client.close()
                self.updates.put(('connection', False, f'Déconnecté : {exc}'))
            self.stop.wait(.07)
        client.close()


class ClientGui:
    def __init__(self, root, host, port):
        self.root = root
        self.commands = queue.Queue()
        self.updates = queue.Queue()
        self.poll_enabled = threading.Event()
        self.poll_enabled.set()
        self.stop = threading.Event()
        self.cible = Cible(host, port)
        self.worker = Worker(self.cible, self.commands, self.updates, self.poll_enabled, self.stop)
        self.rows = {}
        self.decoded = {1: {}, 2: {}, 3: {}, 4: {}}
        root.title('MODBUS LAB — Pupitre PC (client)')
        root.geometry('990x820')
        root.minsize(820, 640)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Lab.Treeview', background=PANEL, fieldbackground=PANEL,
                        foreground=WHITE, rowheight=27, borderwidth=0,
                        font=(FONT, 10))
        style.configure('Lab.Treeview.Heading', background=PANEL2,
                        foreground=WHITE, font=(FONT, 10, 'bold'))
        style.map('Lab.Treeview', background=[('selected', '#2c5e86')])

        head = tk.Frame(root, bg=BG)
        head.pack(fill='x', padx=22, pady=(17, 12))
        label(head, 'PUPITRE MODBUS', 23, True, BLUE).pack(side='left')
        BarreServeur(head, self.cible, self.change_server, BG, WHITE, FONT,
                     button_bg=PANEL2).pack(side='left', padx=(22, 0), pady=6)
        self.connected = label(head, f'● Connexion à {host}:{port}…', 11,
                               True, ORANGE)
        self.connected.pack(side='right', pady=8, padx=(12, 0))

        content = tk.Frame(root, bg=BG)
        content.pack(fill='x', padx=22)
        left = tk.Frame(content, bg=PANEL)
        left.pack(side='left', fill='both', expand=True, padx=(0, 12))
        right = tk.Frame(content, bg=PANEL, width=300)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)

        label(left, 'COMMANDES DE LA MACHINE', 13, True, WHITE, PANEL).pack(anchor='w', padx=16, pady=(16, 11))
        buttons = tk.Frame(left, bg=PANEL)
        buttons.pack(fill='x', padx=12, pady=(0, 11))
        btn(buttons, '▶ MARCHE', lambda: self.order('coil', 0, True,
                                                  'FC05 • Démarrer moteur'), '#136648').pack(side='left', padx=4)
        btn(buttons, '■ ARRÊT', lambda: self.order('coil', 0, False,
                                                 'FC05 • Arrêter moteur'), '#913e4e').pack(side='left', padx=4)
        btn(buttons, '↻ RAZ compteur', lambda: self.order('coil', 2, True,
                                                         'FC05 • RAZ compteur')).pack(side='left', padx=4)
        btn(left, '✓ ACQUITTER UN DÉFAUT', lambda: self.order('coil', 1, True,
                                           'FC05 • Acquit défaut'), '#665123').pack(anchor='w', padx=16, pady=(0, 10))

        regline = tk.Frame(left, bg=PANEL)
        regline.pack(fill='x', padx=16, pady=(0, 15))
        label(regline, 'Vitesse', 10, bg=PANEL).pack(side='left', padx=(0, 4))
        self.speed = tk.IntVar(value=50)
        tk.Spinbox(regline, from_=1, to=100, width=5, textvariable=self.speed,
                   relief='flat', bg=PANEL2, fg=WHITE, buttonbackground=PANEL2,
                   insertbackground=WHITE).pack(side='left')
        btn(regline, 'Envoyer', self.send_speed, '#255a86').pack(side='left', padx=(7, 16))
        label(regline, 'Objectif', 10, bg=PANEL).pack(side='left', padx=(0, 4))
        self.target = tk.IntVar(value=0)
        tk.Spinbox(regline, from_=0, to=5000, width=6, textvariable=self.target,
                   relief='flat', bg=PANEL2, fg=WHITE, buttonbackground=PANEL2,
                   insertbackground=WHITE).pack(side='left')
        btn(regline, 'Envoyer', self.send_target, '#255a86').pack(side='left', padx=(7, 0))

        self.state = label(left, 'MACHINE NON INTERROGÉE', 16, True, MUTED, PANEL)
        self.state.pack(anchor='w', padx=16, pady=(1, 15))

        label(right, 'VALEURS RETOURNÉES', 13, True, WHITE, PANEL).pack(anchor='w', padx=14, pady=(16, 10))
        self.values = {}
        for name in ['Cartons', 'Moteur', 'Capteur S1', 'Capteur S2',
                     'Défaut', 'Sur le tapis', 'Vitesse', 'Objectif']:
            row = tk.Frame(right, bg=PANEL)
            row.pack(fill='x', padx=14, pady=1)
            label(row, name, 11, fg=MUTED, bg=PANEL).pack(side='left')
            self.values[name] = label(row, '—', 11, True, WHITE, PANEL)
            self.values[name].pack(side='right')

        tools = tk.Frame(root, bg=PANEL)
        tools.pack(fill='x', padx=22, pady=10)
        self.auto = tk.BooleanVar(value=True)
        tk.Checkbutton(tools, text='Lecture automatique des registres (toutes les 0,9 s)',
                       variable=self.auto, command=self.toggle_poll, bg=PANEL,
                       fg=WHITE, activebackground=PANEL, activeforeground=WHITE,
                       selectcolor=BG, font=(FONT, 10)).pack(side='left', padx=12, pady=10)
        btn(tools, 'Lire maintenant', self.poll_now).pack(side='right', padx=12, pady=5)

        rawbox = tk.Frame(root, bg=PANEL)
        rawbox.pack(fill='x', padx=22, pady=(0, 12))
        raw = tk.Frame(rawbox, bg=PANEL)
        raw.pack(fill='x')
        label(raw, 'TRAME PDU MANUELLE', 10, True, BLUE, PANEL).pack(side='left', padx=12)
        self.raw = tk.StringVar(value='04 00 00 00 07')
        tk.Entry(raw, textvariable=self.raw, width=26, bg='#0d1825', fg=GREEN,
                 insertbackground=WHITE, relief='flat', font=('Courier', 11)).pack(side='left', padx=8, ipady=7)
        btn(raw, 'Envoyer PDU', self.send_raw, '#265781').pack(side='left', padx=4, pady=7)
        btn(raw, 'Décoder', self.decode_raw, '#265781').pack(side='left', padx=4, pady=7)
        label(raw, 'PDU = FC + adresse\n+ quantité/valeur', 9, fg=MUTED,
              bg=PANEL, justify='right').pack(side='right', padx=10)
        # Résultat de la dernière PDU manuelle : lisible sans chercher dans le journal.
        result = tk.Frame(rawbox, bg=PANEL)
        result.pack(fill='x', padx=12, pady=(0, 7))
        self.raw_pair = None
        self.raw_result = tk.Label(result, text='Dernière PDU manuelle : aucune pour l’instant.',
                                   bg=PANEL, fg=MUTED, font=('Courier', 10),
                                   justify='left', anchor='w')
        self.raw_result.pack(side='left', fill='x', expand=True)

        frame = tk.Frame(root, bg=PANEL)
        frame.pack(fill='both', expand=True, padx=22, pady=(0, 16))
        bar = tk.Frame(frame, bg=PANEL)
        bar.pack(fill='x', padx=12, pady=(11, 5))
        label(bar, 'JOURNAL DES ÉCHANGES (vraies trames TCP)', 12, True,
              WHITE, PANEL).pack(side='left')
        btn(bar, 'Vider', self.clear).pack(side='right')
        btn(bar, 'Décoder la trame', self.decode_selected, '#265781').pack(side='right', padx=8)
        options = tk.Frame(frame, bg=PANEL)
        options.pack(fill='x', padx=12, pady=(0, 5))
        self.hide_auto = tk.BooleanVar(value=False)
        self.follow = tk.BooleanVar(value=True)
        for text, var, cmd in [('Masquer les lectures automatiques', self.hide_auto, None),
                               ('Défilement auto (se fige quand on clique une ligne)',
                                self.follow, self.toggle_follow)]:
            tk.Checkbutton(options, text=text, variable=var, command=cmd, bg=PANEL,
                           fg=WHITE, activebackground=PANEL, activeforeground=WHITE,
                           selectcolor=BG, font=(FONT, 10)).pack(side='left', padx=(0, 18))
        wrap = tk.Frame(frame, bg=PANEL)
        wrap.pack(fill='both', expand=True, padx=12)
        self.tree = ttk.Treeview(wrap, columns=('time', 'name', 'result'),
                                 show='headings', style='Lab.Treeview', height=4)
        for col, title, width in [('time', 'Heure', 90), ('name', 'Opération', 520), ('result', 'Résultat', 100)]:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, stretch=col == 'name')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(wrap, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.show_selected)
        self.details = label(frame, 'Cliquer sur une ligne pour voir les octets de la requête et de la réponse.',
                             10, fg=BLUE, bg=PANEL, justify='left', anchor='w')
        self.details.pack(fill='x', padx=13, pady=(8, 11))
        self.note = label(root, 'Attention : les boutons pilotent une machine virtuelle, pas une sécurité réelle.',
                          9, fg=MUTED)
        self.note.pack(anchor='w', padx=22, pady=(0, 8))
        self.worker.start()
        self.tick()

    def change_server(self, host):
        """Nouvelle adresse : les valeurs affichées venaient de l'ancien serveur."""
        self.decoded = {1: {}, 2: {}, 3: {}, 4: {}}
        self.display_values()
        self.state.config(text='MACHINE NON INTERROGÉE', fg=MUTED)

    def order(self, action, addr, value, description):
        self.commands.put((action, addr, value, description))

    def send_speed(self):
        try:
            value = self.speed.get()
            if not 1 <= value <= 100: raise ValueError()
            self.order('register', 0, value, f'FC06 • Vitesse = {value} %')
        except (ValueError, tk.TclError):
            messagebox.showerror('Valeur', 'La vitesse doit être entre 1 et 100.')

    def send_target(self):
        try:
            value = self.target.get()
            if not 0 <= value <= 5000: raise ValueError()
            self.order('register', 1, value, f'FC06 • Objectif = {value}')
        except (ValueError, tk.TclError):
            messagebox.showerror('Valeur', 'L’objectif doit être entre 0 et 5000.')

    def send_raw(self):
        try:
            pdu = bytes.fromhex(self.raw.get().strip())
            if len(pdu) != 5:
                raise ValueError('Ce labo accepte des PDU de 5 octets exactement.')
            self.order('raw', 0, pdu, f'PDU manuel • {hx(pdu)}')
        except ValueError as exc:
            messagebox.showerror('Trame', f'Hexadécimal invalide : {exc}')

    def poll_now(self):
        for fc, n, name in [(1, 3, 'FC01 • Coils'), (2, 2, 'FC02 • Entrées TOR'),
                            (3, 2, 'FC03 • Paramètres'), (4, 7, 'FC04 • Capteurs / état')]:
            self.order('read', 0, (fc, n), name)

    def toggle_poll(self):
        if self.auto.get():
            self.poll_enabled.set()
        else:
            self.poll_enabled.clear()

    def decode_selected(self):
        items = self.tree.selection()
        if not items or items[0] not in self.rows:
            messagebox.showinfo('Décodage', 'Sélectionne d’abord une ligne dans le journal.')
            return
        self.open_decoder(*self.rows[items[0]])

    def decode_raw(self):
        if self.raw_pair is None:
            messagebox.showinfo('Décodage', 'Envoie d’abord une PDU manuelle.')
            return
        self.open_decoder(*self.raw_pair)

    def toggle_follow(self):
        if self.follow.get():
            self.tree.selection_remove(self.tree.selection())
            children = self.tree.get_children()
            if children:
                self.tree.see(children[-1])

    def open_decoder(self, request, response):
        popup = tk.Toplevel(self.root)
        popup.title('Décodeur Modbus TCP — analyse octet par octet')
        popup.geometry('750x650')
        popup.configure(bg=BG)
        label(popup, 'ANALYSE D’UNE TRANSACTION MODBUS TCP', 17, True, BLUE).pack(
            anchor='w', padx=20, pady=(18, 9))
        label(popup, 'La trame MBAP précède la PDU ; les adresses commencent à zéro.',
              10, fg=MUTED).pack(anchor='w', padx=20, pady=(0, 8))
        wrap = tk.Frame(popup, bg=BG)
        wrap.pack(fill='both', expand=True, padx=20, pady=(0, 20))
        decoded = tk.Text(wrap, bg=PANEL, fg=WHITE, relief='flat',
                          font=('Courier', 11), padx=14, pady=14, wrap='word')
        decoded.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(wrap, command=decoded.yview)
        scroll.pack(side='right', fill='y')
        decoded.configure(yscrollcommand=scroll.set)
        decoded.insert('1.0', decode_pair(request, response))
        decoded.configure(state='disabled')

    def clear(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.rows.clear()
        self.details.config(text='Journal visuel effacé.')

    def show_selected(self, _event=None):
        items = self.tree.selection()
        if items:
            self.follow.set(False)
        if items and items[0] in self.rows:
            req, resp = self.rows[items[0]]
            self.details.config(text=f' REQUÊTE : {req}\n RÉPONSE : {resp}')

    def display_values(self):
        ir = self.decoded[4]
        hr = self.decoded[3]
        field_values = {'Cartons': ir.get(0), 'Moteur': ir.get(1),
                        'Capteur S1': ir.get(2), 'Capteur S2': ir.get(3),
                        'Défaut': ir.get(4), 'Sur le tapis': ir.get(5),
                        'Vitesse': hr.get(0), 'Objectif': hr.get(1)}
        for name, val in field_values.items():
            self.values[name].config(text=str(val) if val is not None else '—')
        states = {0: ('MACHINE ARRÊTÉE', MUTED), 1: ('MACHINE EN MARCHE', GREEN),
                  2: ('DÉFAUT — ACQUITTEMENT REQUIS', RED),
                  3: ('OBJECTIF ATTEINT', ORANGE)}
        self.state.config(text=states.get(ir.get(6), ('ÉTAT INCONNU', MUTED))[0],
                          fg=states.get(ir.get(6), ('?', MUTED))[1])

    def tick(self):
        try:
            for _ in range(150):
                try:
                    event = self.updates.get_nowait()
                except queue.Empty:
                    break
                kind = event[0]
                if kind == 'connection':
                    _, connected, desc = event
                    self.connected.config(text=('● ' if connected is not False else '○ ') + desc,
                                          fg={True: GREEN, False: RED}.get(connected, ORANGE))
                elif kind == 'values':
                    _, fc, offset, data = event
                    for i, value in enumerate(data):
                        self.decoded[fc][offset + i] = value
                    self.display_values()
                elif kind == 'trace':
                    _, stamp, description, req, resp, failed, auto = event
                    if auto and self.hide_auto.get():
                        continue
                    item = self.tree.insert('', 'end', values=(stamp, description,
                                                               'EXCEPTION' if failed else 'OK'))
                    self.rows[item] = (req, resp)
                    if self.follow.get():
                        self.tree.see(item)
                    # Limiter la taille, sans jamais supprimer la ligne sélectionnée.
                    selected = set(self.tree.selection())
                    children = self.tree.get_children()
                    for old in children[:max(0, len(children) - 230)]:
                        if old not in selected:
                            self.tree.delete(old)
                            self.rows.pop(old, None)
                elif kind == 'raw':
                    _, req, resp, error = event
                    self.raw_pair = (req, resp)
                    status = f'EXCEPTION — {error}' if error else 'OK'
                    self.raw_result.config(
                        text=f'REQUÊTE : {req}\nRÉPONSE : {resp}   ({status})',
                        fg=RED if error else GREEN)
                elif kind == 'note':
                    self.note.config(text=event[1], fg=RED)
        finally:
            if not self.stop.is_set():
                self.root.after(90, self.tick)

    def close(self):
        self.stop.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Pupitre client Modbus TCP, sans matériel.')
    parser.add_argument('--host', default='127.0.0.1', help='Adresse du serveur Modbus TCP')
    parser.add_argument('--port', type=int, default=1502)
    args = parser.parse_args()
    root = tk.Tk()
    ClientGui(root, args.host, args.port)
    root.mainloop()


if __name__ == '__main__':
    main()
