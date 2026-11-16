"""Adresse du serveur visé par un pupitre, modifiable pendant l'exécution.

- Cible : adresse partagée entre l'interface et les threads réseau.
- BarreServeur : champ « Serveur » + bouton « Connecter » dans l'en-tête d'un pupitre.
- lire_memoire / memoriser : dernière adresse utilisée (fichier serveur_lab.txt),
  partagée avec lancer_tp.sh et demarrer.py.
"""
import errno
import os
import socket
import threading
import tkinter as tk

from bouton import BoutonPlat

FICHIER_MEMOIRE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'serveur_lab.txt')
LOCALES = {'127.0.0.1', 'localhost', '::1'}


def lire_memoire():
    try:
        with open(FICHIER_MEMOIRE, encoding='utf-8') as f:
            return f.read().strip() or None
    except OSError:
        return None


def memoriser(host):
    """Retient une adresse distante (les adresses locales ne sont pas retenues)."""
    if host in LOCALES:
        return
    try:
        with open(FICHIER_MEMOIRE, 'w', encoding='utf-8') as f:
            f.write(host + '\n')
    except OSError:
        pass


def message_erreur(exc):
    """Erreur réseau en message court, avec une piste de diagnostic."""
    if isinstance(exc, ConnectionRefusedError):
        return 'refusée (simulateur arrêté ?)'
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return 'pas de réponse (IP, pare-feu ?)'
    if isinstance(exc, socket.gaierror):
        return 'adresse inconnue'
    if getattr(exc, 'errno', None) in (errno.EHOSTDOWN, errno.EHOSTUNREACH, errno.ENETUNREACH):
        return 'machine injoignable'
    return str(exc)


def adresse_valide(host):
    return bool(host) and len(host) <= 253 and not any(c.isspace() for c in host)


class Cible:
    """Le thread réseau compare `version` à la dernière vue : si elle a changé,
    il ferme sa connexion et se reconnecte à la nouvelle adresse."""
    def __init__(self, host, port):
        self._lock = threading.Lock()
        self._host, self._port, self._version = host, port, 0

    def changer(self, host):
        with self._lock:
            self._host = host
            self._version += 1

    def lire(self):
        with self._lock:
            return self._host, self._port, self._version

    def suivre(self, client, vue):
        """Applique au client un éventuel changement d'adresse.
        Renvoie (nouvelle version vue, True si l'adresse a changé)."""
        host, port, version = self.lire()
        if version == vue:
            return vue, False
        client.close()
        client.host, client.port = host, port
        return version, True


class BarreServeur(tk.Frame):
    def __init__(self, parent, cible, on_change, bg, fg, font, entry_bg='#0d1825',
                 button_bg='#223248'):
        super().__init__(parent, bg=bg)
        self.cible, self.on_change, self.entry_bg = cible, on_change, entry_bg
        host, port, _ = cible.lire()
        tk.Label(self, text='Serveur', bg=bg, fg=fg, font=(font, 10)).pack(side='left')
        self.var = tk.StringVar(value=host)
        self.entry = tk.Entry(self, textvariable=self.var, width=15, bg=entry_bg, fg=fg,
                              relief='flat', insertbackground=fg, font=('Courier', 11))
        self.entry.pack(side='left', padx=(6, 2), ipady=3)
        self.entry.bind('<Return>', lambda _e: self.appliquer())
        tk.Label(self, text=f':{port}', bg=bg, fg=fg, font=('Courier', 11)).pack(side='left')
        BoutonPlat(self, 'Connecter', self.appliquer, bg=button_bg, fg=fg,
                   font=(font, 10, 'bold'), padx=10, pady=4).pack(side='left', padx=(8, 0))

    def appliquer(self):
        host = self.var.get().strip()
        if not adresse_valide(host):
            self.entry.configure(bg='#5a1f2a')
            self.after(700, lambda: self.entry.configure(bg=self.entry_bg))
            return
        self.var.set(host)
        self.cible.changer(host)
        memoriser(host)
        self.on_change(host)
