"""Génère Documentation_technique_convoyeur.pdf.

Nécessite ReportLab (hors bibliothèque standard, contrairement au reste du TP) et les
polices Arial de macOS :
    python3 -m venv .venv && .venv/bin/pip install reportlab
    .venv/bin/python generer_doc.py
Les trames d'exemple sont calculées par le vrai moteur (modbus_core).
"""
import os
import struct
import sys
import time

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)
import modbus_core as mc  # noqa: E402

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Circle, Polygon
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle, PageBreak, KeepTogether, CondPageBreak)

F = '/System/Library/Fonts/Supplemental/'
pdfmetrics.registerFont(TTFont('Arial', F + 'Arial.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Bold', F + 'Arial Bold.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Italic', F + 'Arial Italic.ttf'))
pdfmetrics.registerFont(TTFont('Mono', F + 'Courier New.ttf'))
pdfmetrics.registerFont(TTFont('Mono-Bold', F + 'Courier New Bold.ttf'))
from reportlab.pdfbase.pdfmetrics import registerFontFamily  # noqa: E402
registerFontFamily('Arial', normal='Arial', bold='Arial-Bold', italic='Arial-Italic',
                   boldItalic='Arial-Bold')
registerFontFamily('Mono', normal='Mono', bold='Mono-Bold', italic='Mono', boldItalic='Mono-Bold')

NAVY = colors.HexColor('#16324f')
BLUE = colors.HexColor('#2f6fae')
LIGHT = colors.HexColor('#e9f1f9')
GREY = colors.HexColor('#5d6b7a')
LINE = colors.HexColor('#c5d3e0')
GREEN = colors.HexColor('#2e8b62')
RED = colors.HexColor('#b8404f')
ORANGE = colors.HexColor('#c9822b')

st = {
    'title': ParagraphStyle('title', fontName='Arial-Bold', fontSize=26, leading=31, textColor=NAVY),
    'subtitle': ParagraphStyle('subtitle', fontName='Arial', fontSize=13, leading=18, textColor=GREY),
    'h1': ParagraphStyle('h1', fontName='Arial-Bold', fontSize=15, leading=19, textColor=NAVY,
                         spaceBefore=14, spaceAfter=7),
    'h2': ParagraphStyle('h2', fontName='Arial-Bold', fontSize=11.5, leading=15, textColor=BLUE,
                         spaceBefore=9, spaceAfter=4),
    'body': ParagraphStyle('body', fontName='Arial', fontSize=9.8, leading=13.6, spaceAfter=5),
    'small': ParagraphStyle('small', fontName='Arial', fontSize=8.4, leading=11, textColor=GREY),
    'cell': ParagraphStyle('cell', fontName='Arial', fontSize=8.8, leading=11.2),
    'cellb': ParagraphStyle('cellb', fontName='Arial-Bold', fontSize=8.8, leading=11.2),
    'head': ParagraphStyle('head', fontName='Arial-Bold', fontSize=8.8, leading=11.2,
                           textColor=colors.white),
    'mono': ParagraphStyle('mono', fontName='Mono', fontSize=8.6, leading=11),
    'note': ParagraphStyle('note', fontName='Arial', fontSize=9.2, leading=12.8),
    'caption': ParagraphStyle('caption', fontName='Arial-Italic', fontSize=8.4, leading=11,
                              textColor=GREY, alignment=TA_CENTER, spaceAfter=8),
}


def P(text, style='body'):
    return Paragraph(text, st[style])


def table(rows, widths, mono_cols=(), header=True, zebra=True):
    data = []
    for r, row in enumerate(rows):
        line = []
        for c, cell in enumerate(row):
            if isinstance(cell, str):
                if header and r == 0:
                    cell = Paragraph(cell, st['head'])
                elif c in mono_cols:
                    cell = Paragraph(cell, st['mono'])
                else:
                    cell = Paragraph(cell, st['cell'])
            line.append(cell)
        data.append(line)
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [('GRID', (0, 0), (-1, -1), .5, LINE),
             ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
             ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
             ('LEFTPADDING', (0, 0), (-1, -1), 5), ('RIGHTPADDING', (0, 0), (-1, -1), 5)]
    if header:
        style.append(('BACKGROUND', (0, 0), (-1, 0), NAVY))
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if i % 2 == 0:
                style.append(('BACKGROUND', (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


def note(text, color=BLUE):
    t = Table([[Paragraph(text, st['note'])]], colWidths=[170 * mm])
    t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), LIGHT),
                           ('LINEBEFORE', (0, 0), (0, -1), 3, color),
                           ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                           ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    return t


# ---------------------------------------------------------------- trames réelles
def frames():
    """Exécute les PDU sur le vrai moteur du simulateur pour obtenir les octets exacts."""
    m = mc.machine
    m.count, m.speed, m.target, m.command_run = 12, 50, 0, True
    m.boxes = [.2, .55, .8]
    tx = [0]

    def run(pdu_hex, prepare=None):
        if prepare:
            prepare()
        pdu = bytes.fromhex(pdu_hex)
        tx[0] += 1
        req = struct.pack('>HHHB', tx[0], 0, len(pdu) + 1, 1) + pdu
        rpdu = mc.process_pdu(pdu)
        resp = struct.pack('>HHHB', tx[0], 0, len(rpdu) + 1, 1) + rpdu
        return mc.hx(req), mc.hx(resp), rpdu

    out = []
    out.append(('Lire les 7 Input Registers (état complet)', *run('04 00 00 00 07')))
    out.append(('Lire les 3 coils', *run('01 00 00 00 03')))
    out.append(('Lire les 2 Discrete Inputs', *run('02 00 00 00 02')))
    out.append(('Lire vitesse et objectif (HR0, HR1)', *run('03 00 00 00 02')))
    out.append(('Arrêter le convoyeur (coil 0 = 0)', *run('05 00 00 00 00')))
    out.append(('Démarrer le convoyeur (coil 0 = 1)', *run('05 00 00 FF 00')))
    out.append(('Régler la vitesse à 80 % (HR0 = 0x0050)', *run('06 00 00 00 50')))
    exc = []
    exc.append(('Fonction inconnue 0x2B', *run('2B 00 00 00 01')))
    exc.append(('Lecture hors table : IR5 à IR7', *run('04 00 05 00 03')))
    exc.append(('Vitesse = 0 (hors plage 1 à 100)', *run('06 00 00 00 00')))

    def fault():
        m.inject_jam()
    exc.append(('Marche demandée pendant un bourrage', *run('05 00 00 FF 00', fault)))
    return out, exc


EXAMPLES, EXCEPTIONS = frames()


# ---------------------------------------------------------------- dessins
def arrow(d, x1, y1, x2, y2, color=NAVY, width=1.3):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=width))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    s = 6
    d.add(Polygon([x2, y2,
                   x2 - s * math.cos(a - .4), y2 - s * math.sin(a - .4),
                   x2 - s * math.cos(a + .4), y2 - s * math.sin(a + .4)],
                  fillColor=color, strokeColor=color))


def box(d, x, y, w, h, title, lines=(), fill=LIGHT, stroke=NAVY, tcolor=NAVY):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=stroke, strokeWidth=1))
    d.add(String(x + w / 2, y + h - 15, title, fontName='Arial-Bold', fontSize=9.5,
                 fillColor=tcolor, textAnchor='middle'))
    for i, text in enumerate(lines):
        d.add(String(x + w / 2, y + h - 29 - i * 11, text, fontName='Arial', fontSize=8,
                     fillColor=GREY, textAnchor='middle'))


def architecture():
    d = Drawing(480, 150)
    box(d, 0, 78, 140, 62, 'Pupitre PC', ['pupitre_pc.py', 'client Modbus TCP'])
    box(d, 0, 6, 140, 62, 'ESP32 / autre client', ['esp32_client_modbus.ino', 'client Modbus TCP'])
    box(d, 300, 24, 180, 100, 'Simulateur', ['simulateur_modbus.py', 'serveur Modbus TCP',
                                             'Unit ID 1', 'machine virtuelle + journal'],
        fill=colors.HexColor('#e6f4ee'), stroke=GREEN, tcolor=GREEN)
    arrow(d, 142, 109, 297, 86)
    arrow(d, 142, 37, 297, 62)
    d.add(String(220, 110, 'TCP 1502', fontName='Arial-Bold', fontSize=8.5, fillColor=BLUE,
                 textAnchor='middle'))
    d.add(String(220, 30, 'requête / réponse', fontName='Arial', fontSize=8, fillColor=GREY,
                 textAnchor='middle'))
    return d


def deployment():
    d = Drawing(480, 170)
    # Conteneurs machines
    for x, w, name in [(0, 175, 'MACHINE PUPITRE (une ou plusieurs)'), (300, 180, 'MACHINE LAB')]:
        d.add(Rect(x, 0, w, 150, rx=7, ry=7, fillColor=None, strokeColor=GREY,
                   strokeWidth=.8, strokeDashArray=[4, 3]))
        d.add(String(x + w / 2, 156, name, fontName='Arial-Bold', fontSize=8.5, fillColor=GREY,
                     textAnchor='middle'))
    box(d, 12, 80, 151, 56, 'Pupitre convoyeur', ['pupitre_pc.py --host IP_LAB'])
    box(d, 12, 12, 151, 56, 'Pupitre robot', ['pupitre_robot.py --host IP_LAB'])
    box(d, 312, 24, 156, 100, 'Simulateur', ['simulateur_modbus.py', '--host 0.0.0.0',
                                             'écoute sur toutes les interfaces', 'IP_LAB : 1502 et 5020'],
        fill=colors.HexColor('#e6f4ee'), stroke=GREEN, tcolor=GREEN)
    arrow(d, 165, 108, 309, 90)
    arrow(d, 165, 40, 309, 58)
    d.add(String(237, 110, 'TCP 1502', fontName='Arial-Bold', fontSize=8.5, fillColor=BLUE,
                 textAnchor='middle'))
    d.add(String(237, 30, 'TCP 5020', fontName='Arial-Bold', fontSize=8.5, fillColor=BLUE,
                 textAnchor='middle'))
    d.add(String(237, 72, 'réseau local', fontName='Arial', fontSize=8, fillColor=GREY,
                 textAnchor='middle'))
    d.add(String(237, 62, '(Wi-Fi / Ethernet)', fontName='Arial', fontSize=8, fillColor=GREY,
                 textAnchor='middle'))
    return d


def conveyor():
    d = Drawing(480, 140)
    x0, x1, y = 40, 440, 40
    d.add(Rect(x0 - 10, y, x1 - x0 + 20, 18, fillColor=colors.HexColor('#3b4f63'),
               strokeColor=NAVY))
    for x in range(x0, x1 + 1, 40):
        d.add(Circle(x, y - 6, 6, fillColor=colors.HexColor('#7d93a8'), strokeColor=NAVY))
    for x in (120, 250, 360):
        d.add(Rect(x, y + 18, 34, 26, fillColor=colors.HexColor('#d99a5e'),
                   strokeColor=colors.HexColor('#84532f')))
    for x, name, sub in [(x0 + 15, 'S1', 'IR2 · entrée'), (x1 - 5, 'S2', 'IR3 · sortie')]:
        d.add(Circle(x, y + 72, 6, fillColor=GREEN, strokeColor=GREEN))
        d.add(Line(x, y + 66, x, y + 20, strokeColor=GREEN, strokeDashArray=[3, 3]))
        d.add(String(x, y + 84, f'{name} ({sub})', fontName='Arial-Bold', fontSize=8.5,
                     fillColor=NAVY, textAnchor='middle'))
    arrow(d, 180, 104, 300, 104, BLUE)
    d.add(String(240, 109, 'sens de défilement', fontName='Arial', fontSize=8, fillColor=BLUE,
                 textAnchor='middle'))
    d.add(String(x0 - 10, y - 26, 'Apparition des cartons', fontName='Arial', fontSize=8,
                 fillColor=GREY))
    d.add(String(x1 + 10, y - 26, 'Sortie : compteur IR0 + 1', fontName='Arial', fontSize=8,
                 fillColor=GREY, textAnchor='end'))
    return d


def states():
    d = Drawing(480, 190)
    nodes = {0: (20, 120, 'IR6 = 0', 'ARRÊT', GREY),
             1: (190, 120, 'IR6 = 1', 'MARCHE', GREEN),
             3: (360, 120, 'IR6 = 3', 'OBJECTIF ATTEINT', ORANGE),
             2: (190, 10, 'IR6 = 2', 'DÉFAUT', RED)}
    w, h = 110, 44
    for _, (x, y, a, b, c) in nodes.items():
        d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=colors.white, strokeColor=c, strokeWidth=1.6))
        d.add(String(x + w / 2, y + 26, b, fontName='Arial-Bold', fontSize=9.5, fillColor=c,
                     textAnchor='middle'))
        d.add(String(x + w / 2, y + 12, a, fontName='Mono', fontSize=8.5, fillColor=NAVY,
                     textAnchor='middle'))
    lab = lambda x, y, t, anchor='middle': d.add(String(x, y, t, fontName='Arial', fontSize=7.6,
                                                        fillColor=NAVY, textAnchor=anchor))
    arrow(d, 130, 150, 188, 150); lab(159, 156, 'coil 0 = 1')
    arrow(d, 188, 134, 132, 134); lab(160, 124, 'coil 0 = 0')
    arrow(d, 302, 142, 358, 142); lab(330, 150, 'IR0 ≥ HR1 > 0')
    # vers défaut
    arrow(d, 235, 118, 235, 56, RED); lab(238, 92, 'bourrage / AU', 'start')
    # défaut -> arrêt
    arrow(d, 188, 32, 75, 32); arrow(d, 75, 32, 75, 117)
    lab(82, 40, 'cause levée +', 'start'); lab(82, 20, 'acquittement (coil 1 = 1)', 'start')
    # objectif -> arrêt
    d.add(Line(415, 164, 415, 180, strokeColor=NAVY, strokeWidth=1.3))
    d.add(Line(415, 180, 75, 180, strokeColor=NAVY, strokeWidth=1.3))
    arrow(d, 75, 180, 75, 166)
    lab(245, 184, 'RAZ compteur (coil 2 = 1) ou objectif HR1 relevé au-dessus de IR0')
    return d


# ---------------------------------------------------------------- page
def on_page(canv, doc):
    canv.saveState()
    canv.setStrokeColor(LINE)
    canv.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canv.setFont('Arial', 8)
    canv.setFillColor(GREY)
    canv.drawString(20 * mm, 10.5 * mm, 'MODBUS LAB V2 — Documentation technique du convoyeur virtuel')
    canv.drawRightString(190 * mm, 10.5 * mm, f'Page {doc.page}')
    canv.restoreState()


def on_first(canv, doc):
    canv.saveState()
    canv.setFillColor(NAVY)
    canv.rect(0, A4[1] - 12 * mm, A4[0], 12 * mm, stroke=0, fill=1)
    canv.restoreState()
    on_page(canv, doc)


story = []
story += [Spacer(1, 14 * mm),
          P('Convoyeur industriel virtuel', 'title'),
          Spacer(1, 3),
          P('Documentation technique — interface Modbus TCP', 'subtitle'),
          Spacer(1, 2),
          P(f'MODBUS LAB V2 · édition du {time.strftime("%d/%m/%Y")}', 'small'),
          Spacer(1, 9 * mm)]

summary = table([
    ['Caractéristique', 'Valeur'],
    ['Protocole', 'Modbus TCP (en-tête MBAP + PDU)'],
    ['Adresse du serveur', '127.0.0.1 (tout sur un poste) ou IP de la machine lab '
     '(mode lab : <font name="Mono">--host 0.0.0.0</font>, voir § 9)'],
    ['Port TCP', '<b>1502</b> (au lieu de 502, port privilégié)'],
    ['Unit ID', '<b>1</b> (toute autre valeur est ignorée : pas de réponse)'],
    ['Codes fonction', '01, 02, 03, 04, 05, 06'],
    ['Longueur de PDU', '5 octets : code fonction + adresse (2) + quantité ou valeur (2)'],
    ['Adressage', 'Offsets en base 0, une numérotation par table'],
    ['Ordre des octets', 'Big-endian (octet de poids fort en premier)'],
    ['Inactivité', 'Connexion fermée par le serveur après 12 s sans requête'],
    ['Clients simultanés', 'Plusieurs (un fil d\'exécution par connexion)'],
], [52 * mm, 118 * mm])
story += [P('Fiche résumé', 'h2'), summary, Spacer(1, 6 * mm)]
story += [note('<b>Usage pédagogique.</b> Le convoyeur est une machine simulée. L\'arrêt d\'urgence '
               'virtuel illustre un verrouillage logiciel ; il ne constitue en aucun cas un '
               'dispositif de sécurité pour une machine réelle.', ORANGE)]
story.append(PageBreak())

# 1. Architecture
story += [P('1. Architecture', 'h1'),
          P('Le simulateur joue le rôle de l\'automate : il est <b>serveur</b> Modbus TCP et contient '
            'la machine virtuelle. Les pupitres et l\'ESP32 sont des <b>clients</b> : ils envoient une '
            'requête, le serveur répond. Les échanges passent réellement par la pile TCP/IP du '
            'système, y compris quand tout tourne sur le même ordinateur.'),
          architecture(),
          P('Figure 1 — Clients et serveur Modbus TCP', 'caption'),
          P('Le simulateur peut aussi héberger le robot Ned2 virtuel sur le port 5020. Ce document '
            'ne traite que du convoyeur (port 1502).', 'small'),
          Spacer(1, 5),
          P('Les clients et le serveur peuvent tourner sur le même ordinateur (adresse 127.0.0.1) ou sur '
            '<b>des machines différentes</b> du même réseau : le simulateur sur une machine « lab », '
            'les pupitres sur une ou plusieurs machines « pupitre » (voir § 9).')]

# 2. Fonctionnement
story += [P('2. Fonctionnement de la machine', 'h1'),
          conveyor(),
          P('Figure 2 — Tapis, capteurs et sens de défilement', 'caption'),
          P('Lorsque le convoyeur est en marche :'),
          table([
              ['Élément', 'Comportement'],
              ['Apparition des cartons', 'Un carton toutes les <b>1,35 s</b> en entrée de tapis, '
               'quelle que soit la vitesse.'],
              ['Capteur S1 (IR2)', 'Vaut 1 pendant <b>0,30 s</b> à chaque apparition de carton.'],
              ['Défilement', 'Vitesse du tapis = 0,075 + 0,0032 × HR0, en longueur de tapis par seconde.'],
              ['Capteur S2 (IR3)', 'Vaut 1 pendant <b>0,45 s</b> quand un carton quitte le tapis.'],
              ['Compteur (IR0)', '+1 à chaque carton sorti. Valeur sur 16 bits (repasse à 0 après 65 535).'],
              ['Cartons sur le tapis (IR5)', 'Nombre de cartons présents entre S1 et S2.'],
          ], [45 * mm, 125 * mm]),
          Spacer(1, 6)]

speeds = [['Vitesse HR0', 'Traversée du tapis', 'Cartons sur le tapis (environ)']]
for v in (1, 25, 50, 75, 100):
    t = 1 / (.075 + .0032 * v)
    speeds.append([f'{v} %', f'{t:.1f} s'.replace('.', ','), f'{t / 1.35:.1f}'.replace('.', ',')])
story += [KeepTogether([P('Temps de traversée selon la vitesse', 'h2'),
                        table(speeds, [40 * mm, 50 * mm, 80 * mm]),
                        P('À cadence d\'apparition fixe, une vitesse faible laisse davantage de '
                          'cartons sur le tapis. Le débit de sortie reste d\'un carton toutes les 1,35 s.',
                          'small')])]
story.append(CondPageBreak(150 * mm))

# 3. Etats
story += [P('3. États et conditions de marche', 'h1'),
          P('L\'état de la machine est lu dans <b>IR6</b>. Le moteur ne tourne (IR1 = 1) que si les trois '
            'conditions suivantes sont réunies : commande de marche active (coil 0 = 1), aucun défaut '
            '(IR4 = 0), objectif non atteint.'),
          states(),
          P('Figure 3 — Diagramme des états (IR6)', 'caption'),
          table([
              ['IR6', 'État', 'Signification', 'Pour en sortir'],
              ['0', 'Arrêt', 'Commande de marche inactive.', 'Écrire coil 0 = 1.'],
              ['1', 'Marche', 'Le tapis avance, les cartons sont produits.',
               'Écrire coil 0 = 0, ou défaut, ou objectif atteint.'],
              ['2', 'Défaut', 'Bourrage ou arrêt d\'urgence virtuel. La commande de marche est '
               'remise à 0.', 'Supprimer la cause, puis acquitter (coil 1 = 1).'],
              ['3', 'Objectif atteint', 'IR0 ≥ HR1 avec HR1 > 0. La commande de marche est remise à 0.',
               'Remettre le compteur à zéro ou relever HR1.'],
          ], [12 * mm, 27 * mm, 70 * mm, 61 * mm]),
          Spacer(1, 4),
          P('Priorité : si un défaut est actif, IR6 vaut 2 même si l\'objectif est atteint.', 'small')]

story += [P('Défauts', 'h2'),
          table([
              ['Code IR4', 'Défaut', 'Origine', 'Acquittement'],
              ['0', 'Aucun', '—', '—'],
              ['1', 'Bourrage', 'Bouton « Créer un bourrage » du simulateur, ou accumulation de '
               '4 cartons en mode poste robot.',
               'Possible seulement après « Libérer le bourrage ».'],
              ['2', 'Arrêt d\'urgence virtuel', 'Bouton « Déclencher » du simulateur.',
               'Possible seulement après « Déverrouiller ».'],
          ], [18 * mm, 33 * mm, 70 * mm, 49 * mm]),
          Spacer(1, 6),
          note('<b>Procédure de redémarrage après défaut :</b> 1) supprimer la cause sur le simulateur ; '
               '2) acquitter par Modbus (FC05, coil 1 = 1) ; 3) relancer (FC05, coil 0 = 1). '
               'Tant que la cause est présente, l\'acquittement est refusé avec l\'<b>exception 04</b>. '
               'Une demande de marche pendant un défaut est elle aussi refusée (exception 04).', RED)]
story.append(PageBreak())

# 4. Table Modbus
story += [P('4. Table Modbus', 'h1'),
          P('Les adresses indiquées sont les <b>offsets transmis dans la trame</b> (base 0). Chaque type '
            'de donnée possède sa propre table : le coil 0 et le registre IR0 n\'ont aucun rapport.'),
          P('Coils — bits en lecture/écriture (FC01, FC05)', 'h2'),
          table([
              ['Offset', 'Accès', 'Nom', 'Description'],
              ['0', 'L / E', 'Marche', '1 = marche demandée, 0 = arrêt. Refusé (exc. 04) en défaut ou '
               'objectif atteint.'],
              ['1', 'E (impulsion)', 'Acquitter', 'Écrire 1 pour acquitter le défaut. Se relit toujours 0.'],
              ['2', 'E (impulsion)', 'RAZ compteur', 'Écrire 1 : compteur à 0, tapis vidé, arrêt. '
               'Se relit toujours 0.'],
          ], [16 * mm, 24 * mm, 28 * mm, 102 * mm]),
          P('Discrete Inputs — bits en lecture seule (FC02)', 'h2'),
          table([
              ['Offset', 'Accès', 'Nom', 'Description'],
              ['0', 'L', 'Défaut', '1 si un défaut est actif ou mémorisé (IR4 ≠ 0).'],
              ['1', 'L', 'Objectif atteint', '1 si HR1 > 0 et IR0 ≥ HR1.'],
          ], [16 * mm, 24 * mm, 28 * mm, 102 * mm]),
          P('Holding Registers — mots de 16 bits en lecture/écriture (FC03, FC06)', 'h2'),
          table([
              ['Offset', 'Accès', 'Nom', 'Plage', 'Description'],
              ['0', 'L / E', 'Vitesse', '1 à 100', 'Vitesse du tapis en %. Valeur par défaut : 50.'],
              ['1', 'L / E', 'Objectif', '0 à 5000', 'Nombre de cartons à produire. 0 = production '
               'continue. Par défaut : 0.'],
          ], [16 * mm, 18 * mm, 22 * mm, 22 * mm, 92 * mm]),
          P('Input Registers — mots de 16 bits en lecture seule (FC04)', 'h2'),
          table([
              ['Offset', 'Nom', 'Valeurs', 'Description'],
              ['0', 'Compteur', '0 à 65 535', 'Nombre de cartons produits.'],
              ['1', 'Moteur', '0 / 1', 'État réel du moteur (et non la commande).'],
              ['2', 'Capteur S1', '0 / 1', 'Entrée du tapis, impulsion de 0,30 s par carton.'],
              ['3', 'Capteur S2', '0 / 1', 'Sortie du tapis, impulsion de 0,45 s par carton.'],
              ['4', 'Code défaut', '0, 1, 2', '0 = aucun, 1 = bourrage, 2 = arrêt d\'urgence virtuel.'],
              ['5', 'Sur le tapis', '0 à n', 'Nombre de cartons présents sur le tapis.'],
              ['6', 'État', '0 à 3', '0 = arrêt, 1 = marche, 2 = défaut, 3 = objectif atteint.'],
          ], [16 * mm, 28 * mm, 24 * mm, 102 * mm]),
          Spacer(1, 6),
          note('<b>Commande et état sont distincts.</b> Le coil 0 indique ce qui est <i>demandé</i>, '
               'IR1 indique ce que fait <i>réellement</i> le moteur. Après un défaut, les deux valent 0 ; '
               'en marche normale, les deux valent 1.')]
story.append(PageBreak())

# 5. Trames
story += [P('5. Format des trames', 'h1'),
          P('Une trame Modbus TCP est composée d\'un en-tête <b>MBAP</b> de 7 octets suivi de la '
            '<b>PDU</b>. Le serveur recopie l\'identifiant de transaction dans sa réponse.'),
          table([
              ['Octets', 'Champ', 'Taille', 'Rôle'],
              ['0–1', 'Transaction ID', '2', 'Numéro choisi par le client, renvoyé à l\'identique.'],
              ['2–3', 'Protocol ID', '2', 'Toujours 0x0000 pour Modbus.'],
              ['4–5', 'Longueur', '2', 'Nombre d\'octets qui suivent : Unit ID + PDU.'],
              ['6', 'Unit ID', '1', '0x01 pour le convoyeur.'],
              ['7', 'Code fonction', '1', 'Début de la PDU.'],
              ['8–11', 'Données', '4', 'Adresse (2 octets) + quantité ou valeur (2 octets).'],
          ], [18 * mm, 30 * mm, 16 * mm, 106 * mm]),
          P('Codage des données dans la réponse', 'h2'),
          table([
              ['Fonction', 'Requête (PDU)', 'Réponse normale (PDU)'],
              ['01 / 02 lecture de bits', 'FC, adresse, quantité',
               'FC, nombre d\'octets, bits regroupés par 8 (bit 0 = premier bit demandé)'],
              ['03 / 04 lecture de mots', 'FC, adresse, quantité',
               'FC, nombre d\'octets (2 × quantité), puis chaque registre sur 2 octets'],
              ['05 écriture d\'un bit', 'FC, adresse, FF 00 (=1) ou 00 00 (=0)', 'Écho de la requête'],
              ['06 écriture d\'un mot', 'FC, adresse, valeur', 'Écho de la requête'],
          ], [36 * mm, 56 * mm, 78 * mm]),
          Spacer(1, 4),
          P('Exemples de trames complètes', 'h2'),
          P('Les octets ci-dessous ont été produits par le moteur du simulateur, avec la machine en marche, '
            '12 cartons comptés, vitesse 50 % et 3 cartons sur le tapis.', 'small')]

rows = [['Opération', 'Requête (MBAP + PDU)', 'Réponse (MBAP + PDU)']]
for name, req, resp, _ in EXAMPLES:
    rows.append([name, req, resp])
story += [table(rows, [44 * mm, 56 * mm, 70 * mm], mono_cols=(1, 2))]
story.append(CondPageBreak(90 * mm))

# 6. Exceptions
story += [P('6. Exceptions Modbus', 'h1'),
          P('Quand une requête ne peut pas être exécutée, le serveur répond par une exception : le code '
            'fonction est renvoyé avec le bit de poids fort à 1 (FC + 0x80), suivi d\'un octet de code.'),
          table([
              ['Code', 'Nom', 'Cas déclencheurs sur le convoyeur'],
              ['01', 'Fonction illégale', 'Code fonction autre que 01 à 06.'],
              ['02', 'Adresse illégale', 'Lecture débordant de la table (adresse + quantité > taille), '
               'coil > 2, Holding Register > 1.'],
              ['03', 'Valeur illégale', 'PDU de longueur différente de 5 octets, quantité 0 ou trop grande, '
               'valeur de coil autre que FF 00 / 00 00, vitesse hors 1 à 100, objectif hors 0 à 5000.'],
              ['04', 'Défaillance de l\'esclave', 'Marche demandée en défaut ou objectif atteint ; '
               'acquittement alors que la cause du défaut est toujours présente.'],
          ], [14 * mm, 38 * mm, 118 * mm]),
          Spacer(1, 6),
          P('Exemples', 'h2')]
rows = [['Cas', 'Requête', 'Réponse', 'Code']]
for name, req, resp, rpdu in EXCEPTIONS:
    rows.append([name, req, resp, f'{rpdu[1]:02X}'])
story += [table(rows, [48 * mm, 56 * mm, 52 * mm, 14 * mm], mono_cols=(1, 2)),
          Spacer(1, 6),
          note('<b>Unit ID incorrect :</b> le serveur ne répond pas du tout. Le client doit donc gérer '
               'un délai d\'attente (timeout). C\'est différent d\'une exception, qui est une vraie réponse.')]
story.append(PageBreak())

# 7. Mode poste robot
story += [P('7. Mode « poste robot »', 'h1'),
          P('Ce mode s\'active depuis la fenêtre du robot Ned2 (case <b>Poste robot : cartons arrêtés en bout '
            'de tapis</b>). Il modifie le comportement du convoyeur pour alimenter le robot :'),
          table([
              ['Élément', 'Mode normal', 'Mode poste robot'],
              ['Apparition', 'Un carton toutes les 1,35 s', 'Un carton toutes les 5 s'],
              ['Bout de tapis', 'Le carton sort et est compté', 'Le carton s\'arrête et attend le robot'],
              ['Capteur S2 (IR3)', 'Impulsion de 0,45 s', '1 tant qu\'un carton attend en bout de tapis'],
              ['Compteur (IR0)', '+1 à la sortie du tapis', '+1 quand le robot saisit un carton'],
              ['Accumulation', '—', 'Les cartons s\'arrêtent les uns derrière les autres'],
              ['Bourrage', 'Uniquement manuel', 'Automatique quand 4 cartons sont accumulés'],
          ], [38 * mm, 60 * mm, 72 * mm]),
          Spacer(1, 4),
          P('En mode poste robot, « Libérer le bourrage » retire la file d\'attente et ne laisse que le carton '
            'de tête.', 'small')]

# 8. Mise en service
story += [P('8. Mise en service', 'h1'),
          table([
              ['Besoin', 'Commande'],
              ['TP convoyeur seul (Mac / Linux)', '<font name="Mono">./lancer_tp.sh convoyeur</font> ou '
               'double-clic sur <font name="Mono">TP_CONVOYEUR_MAC.command</font>'],
              ['TP convoyeur + robot (Mac / Linux)', '<font name="Mono">./lancer_tp.sh robot</font> ou '
               'double-clic sur <font name="Mono">TP_ROBOT_MAC.command</font>'],
              ['Tout lancer (toutes plateformes)', '<font name="Mono">python3 demarrer.py</font>'],
              ['Machine lab (deux machines, § 9)', '<font name="Mono">./lancer_tp.sh lab</font>, '
               '<font name="Mono">TP_LAB_MAC.command</font> ou <font name="Mono">TP_LAB_WINDOWS.bat</font>'],
              ['Machine pupitre (deux machines, § 9)', '<font name="Mono">./lancer_tp.sh pupitre</font>, '
               '<font name="Mono">TP_PUPITRE_MAC.command</font> ou '
               '<font name="Mono">TP_PUPITRE_WINDOWS.bat</font>'],
              ['Simulateur seul', '<font name="Mono">python3 simulateur_modbus.py [options]</font>'],
              ['Pupitre seul', '<font name="Mono">python3 pupitre_pc.py [--host IP] [--port 1502]</font>'],
          ], [62 * mm, 108 * mm]),
          P('Options du simulateur', 'h2'),
          table([
              ['Option', 'Défaut', 'Effet'],
              ['--host', '127.0.0.1', 'Adresse d\'écoute. 0.0.0.0 pour accepter des pupitres distants '
               'ou un ESP32 sur le réseau local.'],
              ['--port', '1502', 'Port TCP du convoyeur.'],
              ['--robot-port', '5020', 'Port du robot Ned2 virtuel.'],
              ['--sans-robot', '—', 'Ne pas simuler le robot.'],
              ['--headless', '—', 'Sans interface graphique : le journal s\'affiche dans le terminal.'],
          ], [30 * mm, 26 * mm, 114 * mm], mono_cols=(0, 1)),
          P('Options des pupitres', 'h2'),
          table([
              ['Option', 'Défaut', 'Effet'],
              ['--host', '127.0.0.1', 'Adresse du serveur. Modifiable aussi en cours d\'exécution : champ '
               '<b>Serveur</b> de l\'en-tête, puis <b>Connecter</b> (ou Entrée).'],
              ['--port', '1502 / 5020', 'Port du convoyeur (pupitre_pc.py) ou du robot (pupitre_robot.py).'],
          ], [30 * mm, 26 * mm, 114 * mm], mono_cols=(0, 1))]
story.append(PageBreak())

# 9. Deux machines
story += [P('9. Lab et pupitres sur deux machines', 'h1'),
          P('Une machine <b>lab</b> fait tourner le simulateur, ouvert au réseau. Une ou plusieurs machines '
            '<b>pupitre</b> le pilotent à travers le réseau local : les trames circulent alors réellement sur '
            'le câble ou le Wi-Fi. Plusieurs pupitres peuvent commander le même convoyeur en même temps.'),
          deployment(),
          P('Figure 4 — Déploiement sur deux machines', 'caption'),
          P('Procédure', 'h2'),
          table([
              ['Étape', 'Machine', 'Action'],
              ['1', 'Lab', 'Lancer <font name="Mono">TP_LAB_MAC.command</font>, '
               '<font name="Mono">TP_LAB_WINDOWS.bat</font> ou <font name="Mono">./lancer_tp.sh lab '
               '[convoyeur|robot]</font>. Choisir le TP. Le lanceur démarre le simulateur avec '
               '<font name="Mono">--host 0.0.0.0</font> et affiche l\'<b>adresse IP à communiquer</b> '
               '(également visible dans l\'en-tête du simulateur).'],
              ['2', 'Lab', 'Si le système le demande, autoriser Python à accepter les connexions entrantes, '
               '<b>sur le réseau privé uniquement</b>.'],
              ['3', 'Pupitre', 'Lancer <font name="Mono">TP_PUPITRE_MAC.command</font>, '
               '<font name="Mono">TP_PUPITRE_WINDOWS.bat</font> ou <font name="Mono">./lancer_tp.sh pupitre '
               '[convoyeur|robot] [IP]</font>. Saisir l\'IP de la machine lab : le lanceur vérifie que les '
               'ports répondent, puis ouvre les pupitres.'],
              ['4', 'Pupitre', 'Au besoin, corriger l\'adresse dans le champ <b>Serveur</b> du pupitre, '
               'sans le relancer.'],
          ], [14 * mm, 20 * mm, 136 * mm]),
          Spacer(1, 4),
          P('La dernière IP saisie est retenue dans <font name="Mono">serveur_lab.txt</font> et proposée au '
            'lancement suivant.', 'small'),
          P('Ports à ouvrir sur la machine lab', 'h2'),
          table([
              ['Port', 'Protocole', 'Service'],
              ['1502', 'TCP entrant', 'Convoyeur (Unit ID 1)'],
              ['5020', 'TCP entrant', 'Robot Ned2 virtuel (TP robot uniquement)'],
          ], [20 * mm, 30 * mm, 120 * mm], mono_cols=(0,)),
          P('Diagnostic côté pupitre', 'h2'),
          table([
              ['Message affiché', 'Cause probable', 'Que faire'],
              ['Échec : refusée (simulateur arrêté ?)', 'La machine lab répond, mais rien n\'écoute sur le port.',
               'Lancer le simulateur en mode lab : en mode local, il n\'écoute que sur 127.0.0.1.'],
              ['Échec : pas de réponse (IP, pare-feu ?)', 'Paquets sans réponse.',
               'Vérifier l\'IP et le pare-feu de la machine lab.'],
              ['Échec : machine injoignable', 'Pas de route vers la machine lab.',
               'Mettre les deux machines sur le même réseau (attention aux Wi-Fi invités qui isolent '
               'les clients).'],
              ['Échec : adresse inconnue', 'Nom d\'hôte non résolu.', 'Saisir l\'adresse IP numérique.'],
          ], [52 * mm, 50 * mm, 68 * mm]),
          Spacer(1, 6),
          KeepTogether([P('Analyse avec Wireshark', 'h2'),
          P('Capturer sur l\'<b>interface réseau réelle</b> (<font name="Mono">en0</font> sur macOS, '
            '« Wi-Fi » ou « Ethernet » sous Windows), et non sur la boucle locale. Filtre : '
            '<font name="Mono">ip.addr == IP_LAB &amp;&amp; tcp.port == 1502</font>. Les en-têtes IP et '
            'Ethernet montrent alors les vraies adresses des deux machines.')]),
          Spacer(1, 4),
          note('<b>Sécurité :</b> avec <font name="Mono">--host 0.0.0.0</font>, le simulateur accepte toute '
               'machine du réseau local, sans authentification ni chiffrement (Modbus n\'en prévoit pas). '
               'À n\'utiliser que sur un réseau de TP isolé, jamais sur un réseau public.', RED),
          Spacer(1, 5),
          note('<b>Délais :</b> le serveur ferme une connexion restée 12 s sans requête. La lecture '
               'automatique du pupitre l\'en empêche, mais un Wi-Fi chargé peut provoquer des '
               'timeouts qu\'on n\'observe jamais en local.', ORANGE)]

out = PROJECT + '/Documentation_technique_convoyeur.pdf'
doc = BaseDocTemplate(out, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=18 * mm, bottomMargin=20 * mm,
                      title='Convoyeur virtuel — Documentation technique',
                      author='MODBUS LAB V2', subject='Interface Modbus TCP du convoyeur')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='f')
doc.addPageTemplates([PageTemplate('first', [frame], onPage=on_first),
                      PageTemplate('rest', [frame], onPage=on_page)])
from reportlab.platypus import NextPageTemplate  # noqa: E402
story.insert(0, NextPageTemplate('rest'))
doc.build(story)
print(out)
