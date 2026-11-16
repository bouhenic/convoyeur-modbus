"""Bouton plat coloré, identique sous Windows, macOS et Linux.

Sous macOS, tk.Button utilise le bouton natif Aqua et ignore la couleur de
fond : le texte blanc devient illisible. Ce bouton est un tk.Label cliquable.
"""
import tkinter as tk


def nuance(couleur, facteur):
    """Éclaircit (facteur > 1) ou assombrit (facteur < 1) une couleur #rrggbb."""
    r, g, b = (int(couleur[i:i + 2], 16) for i in (1, 3, 5))
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(c * facteur))) for c in (r, g, b))


class BoutonPlat(tk.Label):
    def __init__(self, parent, text, command, bg, fg, font, padx=15, pady=10, width=None):
        options = dict(text=text, bg=bg, fg=fg, font=font, padx=padx, pady=pady,
                       cursor='hand2', bd=0, highlightthickness=0)
        if width:
            options['width'] = width
        super().__init__(parent, **options)
        self.command = command
        self.couleurs = {'normal': bg, 'survol': nuance(bg, 1.3), 'appui': nuance(bg, 0.8)}
        self.dedans = False
        self.bind('<Enter>', self._entree)
        self.bind('<Leave>', self._sortie)
        self.bind('<ButtonPress-1>', lambda _e: self.configure(bg=self.couleurs['appui']))
        self.bind('<ButtonRelease-1>', self._relache)

    def _entree(self, _event):
        self.dedans = True
        self.configure(bg=self.couleurs['survol'])

    def _sortie(self, _event):
        self.dedans = False
        self.configure(bg=self.couleurs['normal'])

    def _relache(self, _event):
        self.configure(bg=self.couleurs['survol' if self.dedans else 'normal'])
        if self.dedans and self.command:
            self.command()
