"""Décodeur pédagogique des trames Modbus TCP hexadécimales."""
import struct

FUNCTIONS = {
    1: 'Lire des coils (bits de sortie)',
    2: 'Lire des entrées TOR (bits)',
    3: 'Lire des Holding Registers (16 bits)',
    4: 'Lire des Input Registers (16 bits)',
    5: 'Écrire un coil',
    6: 'Écrire un Holding Register',
    15: 'Écrire plusieurs coils',
    16: 'Écrire plusieurs Holding Registers',
}
EXCEPTIONS = {1: 'Fonction inconnue', 2: 'Adresse de registre inexistante',
              3: 'Valeur ou quantité incorrecte', 4: 'Exécution de la commande impossible'}


def float_lines(data):
    """Interprète des registres deux par deux comme des float32 (Niryo)."""
    lines = [' Lecture en float32 (2 registres, mot de poids fort en premier) :']
    for i in range(0, len(data) - 3, 4):
        value = struct.unpack('>f', data[i:i + 4])[0]
        lines += [f' {data[i:i+4].hex(" ").upper():<12} → {value:.6g}']
    return lines


def decode_frame(frame, is_response=False, floats=False):
    """Liste de lignes lisibles, sans utiliser de dépendance externe."""
    if len(frame) < 8:
        return ['Trame incomplète (au moins 8 octets attendus).']
    tx, proto, length, unit = struct.unpack('>HHHB', frame[:7])
    pdu = frame[7:]
    fc = pdu[0]
    real_fc = fc & 0x7f
    kind = 'RÉPONSE' if is_response else 'REQUÊTE'
    lines = [kind, '─' * 57, 'En-tête MBAP — les 7 premiers octets :',
             f' {frame[:2].hex(" ").upper():<9} Identifiant de transaction : {tx}',
             f' {frame[2:4].hex(" ").upper():<9} Identifiant de protocole : {proto} (0 = Modbus)',
             f' {frame[4:6].hex(" ").upper():<9} Longueur : {length} octets (Unit ID + PDU)',
             f' {frame[6:7].hex(" ").upper():<9} Unit ID : {unit}',
             '', 'PDU — la commande ou les données :',
             f' {fc:02X}       Code fonction : {real_fc:02d} — {FUNCTIONS.get(real_fc,"Inconnue")}']
    if length != len(frame) - 6:
        lines += [' ⚠ Longueur MBAP différente de la longueur reçue !']
    if fc & 0x80:
        if len(pdu) > 1:
            lines += [f' {pdu[1]:02X}       Code exception : {pdu[1]} — {EXCEPTIONS.get(pdu[1],"Inconnu")}']
        return lines
    if not is_response and fc in (15, 16) and len(pdu) >= 6:
        offset, qty, nbytes = struct.unpack('>HHB', pdu[1:6])
        data = pdu[6:]
        lines += [f' {pdu[1:3].hex(" ").upper():<9} Adresse de départ : {offset}',
                  f' {pdu[3:5].hex(" ").upper():<9} Quantité : {qty}',
                  f' {pdu[5]:02X}       Nombre d’octets qui suivent : {nbytes}']
        if fc == 15:
            lines += [f' {data.hex(" ").upper()}   Bits, du bit faible au bit fort :']
            lines += [f'          Coil {offset + i} = {(data[i // 8] >> (i % 8)) & 1}'
                      for i in range(min(qty, len(data) * 8))]
        else:
            for i in range(0, len(data) - 1, 2):
                val = struct.unpack('>H', data[i:i + 2])[0]
                lines += [f' {data[i:i+2].hex(" ").upper():<9} Registre {offset + i // 2} : {val}']
            if floats and len(data) >= 4:
                lines += float_lines(data)
        return lines
    if is_response and fc in (15, 16) and len(pdu) == 5:
        offset, qty = struct.unpack('>HH', pdu[1:])
        return lines + [' Réponse normale : le serveur confirme l’adresse et la quantité.',
                        f' {pdu[1:3].hex(" ").upper():<9} Adresse de départ : {offset}',
                        f' {pdu[3:5].hex(" ").upper():<9} Quantité écrite : {qty}']
    if not is_response:
        if len(pdu) == 5:
            offset, val = struct.unpack('>HH', pdu[1:])
            lines += [f' {pdu[1:3].hex(" ").upper():<9} Adresse (offset dans la table) : {offset}']
            if fc in (1, 2, 3, 4):
                lines += [f' {pdu[3:5].hex(" ").upper():<9} Quantité à lire : {val}']
            elif fc == 5:
                state = 'ON (1)' if val == 0xff00 else 'OFF (0)' if val == 0 else 'Valeur incorrecte'
                lines += [f' {pdu[3:5].hex(" ").upper():<9} Valeur du coil : {state}']
            elif fc == 6:
                lines += [f' {pdu[3:5].hex(" ").upper():<9} Valeur du registre : {val} (décimal)']
        else:
            lines += [' Format PDU non attendu pour ce TP.']
    elif fc in (1, 2, 3, 4) and len(pdu) >= 2:
        n = pdu[1]
        lines += [f' {n:02X}       Nombre d’octets de données : {n}']
        data = pdu[2:]
        if len(data) != n:
            lines += [' ⚠ Longueur des données incorrecte']
        elif fc in (1, 2):
            lines += [f' {data.hex(" ").upper()}   Bits, du bit faible au bit fort :']
            for i in range(n * 8):
                lines += [f'          Bit {i} = {(data[i // 8] >> (i % 8)) & 1}']
                if i >= 7:  # Ce simulateur ne traite que de très petites tables.
                    break
        elif n % 2 == 0:
            for i in range(0, n, 2):
                val = struct.unpack('>H', data[i:i+2])[0]
                lines += [f' {data[i:i+2].hex(" ").upper():<9} Registre reçu {i//2} : {val} (décimal)']
            if floats and n >= 4:
                lines += float_lines(data)
    elif fc in (5, 6):
        lines += [' Réponse normale : le serveur répète la commande reçue.']
        if len(pdu) == 5:
            offset, val = struct.unpack('>HH', pdu[1:])
            lines += [f' {pdu[1:3].hex(" ").upper():<9} Adresse : {offset}',
                      f' {pdu[3:5].hex(" ").upper():<9} Valeur : {val} (décimal)']
    return lines


def decode_pair(req_hex, resp_hex, floats=False):
    try:
        request, response = bytes.fromhex(req_hex), bytes.fromhex(resp_hex)
    except ValueError:
        return 'Octets hexadécimaux invalides.'
    return '\n'.join(decode_frame(request, floats=floats) + ['', '']
                     + decode_frame(response, True, floats))
