#!/usr/bin/env python3
"""Démarre le TP Modbus.

    python3 demarrer.py                       tout sur ce PC (simulateur + pupitres)
    python3 demarrer.py lab [convoyeur|robot]    machine LAB : simulateur seul, ouvert au réseau
    python3 demarrer.py pupitre [convoyeur|robot] [IP]   machine PUPITRE : pupitres vers le lab

Sans convoyeur|robot ni IP, les modes lab et pupitre les demandent.
"""
import argparse
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from modbus_core import local_ipv4  # noqa: E402
from cible import adresse_valide, lire_memoire, memoriser  # noqa: E402

PORT, PORT_ROBOT = 1502, 5020


def script(name, *args):
    return subprocess.Popen([sys.executable, os.path.join(HERE, name), *args])


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def port_ouvert(host, port):
    try:
        socket.create_connection((host, port), timeout=1.5).close()
        return True
    except OSError:
        return False


def demander_mode():
    print('Quel TP ?\n  1) Convoyeur seul\n  2) Convoyeur + robot Ned2')
    choix = input('Choix [1] : ').strip().lower()
    if choix in ('', '1', 'convoyeur'):
        return 'convoyeur'
    if choix in ('2', 'robot'):
        return 'robot'
    raise SystemExit('Choix invalide.')


def demander_hote():
    defaut = lire_memoire()
    if defaut:
        hote = input(f'Adresse IP de la machine lab [{defaut}] : ').strip() or defaut
    else:
        hote = input('Adresse IP de la machine lab (affichée dans sa fenêtre) : ').strip()
    if not adresse_valide(hote):
        raise SystemExit('Adresse invalide.')
    return hote


def verifier_tk():
    try:
        import tkinter
        if tkinter.TkVersion < 8.6:
            print(f'⚠ Tk {tkinter.TkVersion} détecté : l\'affichage risque d\'être blanc ou '
                  'illisible. Utilisez un Python avec Tk 8.6+ (python.org ou Homebrew).')
    except ImportError:
        print('⚠ Tkinter est absent de ce Python.')


def tout_local():
    print('MODBUS LAB V2 : ouverture du simulateur, du pupitre et du pupitre robot…')
    server = script('simulateur_modbus.py')
    try:
        time.sleep(0.7)
        robot = script('pupitre_robot.py')
        client = script('pupitre_pc.py')
        client.wait()
        stop(robot)
    finally:
        stop(server)


def lab(mode):
    args = ['--host', '0.0.0.0'] + (['--sans-robot'] if mode == 'convoyeur' else [])
    print(f'MODBUS LAB V2 — machine LAB ({mode}), simulateur ouvert au réseau…')
    server = script('simulateur_modbus.py', *args)
    try:
        for _ in range(30):
            if port_ouvert('127.0.0.1', PORT) or server.poll() is not None:
                break
            time.sleep(0.2)
        if server.poll() is not None:
            raise SystemExit('✖ Le simulateur n\'a pas démarré (port déjà occupé ?).')
        ports = f'{PORT} convoyeur' + (f', {PORT_ROBOT} robot' if mode == 'robot' else '')
        print(f'\n  Adresse à donner aux pupitres :  {local_ipv4()}   (ports {ports})\n')
        print('  Sur chaque machine pupitre : TP_PUPITRE_WINDOWS.bat ou TP_PUPITRE_MAC.command.')
        print('  Si le pare-feu demande d\'autoriser Python : acceptez sur le réseau PRIVÉ uniquement.')
        print('  Fermer la fenêtre du simulateur arrête le lab.')
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop(server)


def pupitre(mode, hote):
    memoriser(hote)
    print(f'MODBUS LAB V2 — pupitres vers le simulateur {hote} ({mode})…')
    for port in [PORT] + ([PORT_ROBOT] if mode == 'robot' else []):
        if port_ouvert(hote, port):
            print(f'✔ {hote}:{port} répond.')
        else:
            print(f'⚠ {hote}:{port} ne répond pas. Vérifiez que le simulateur est lancé en mode lab,\n'
                  f'  que le pare-feu de la machine lab autorise Python (TCP {PORT} et {PORT_ROBOT})\n'
                  '  et que l\'IP est la bonne. Les pupitres s\'ouvrent quand même : ils réessaient\n'
                  '  seuls, et l\'adresse se corrige dans le champ « Serveur » de leur en-tête.')
    robot = script('pupitre_robot.py', '--host', hote) if mode == 'robot' else None
    client = script('pupitre_pc.py', '--host', hote)
    try:
        client.wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop(client)
        stop(robot)


def main():
    parser = argparse.ArgumentParser(description='Lanceur du TP Modbus.')
    parser.add_argument('role', nargs='?', choices=['local', 'lab', 'pupitre'], default='local')
    parser.add_argument('mode', nargs='?', choices=['convoyeur', 'robot'])
    parser.add_argument('hote', nargs='?', help='IP de la machine lab (mode pupitre)')
    args = parser.parse_args()
    verifier_tk()
    if args.role == 'local':
        tout_local()
        return
    mode = args.mode or demander_mode()
    if args.role == 'lab':
        lab(mode)
    else:
        hote = args.hote or demander_hote()
        if not adresse_valide(hote):
            raise SystemExit('Adresse invalide.')
        pupitre(mode, hote)


if __name__ == '__main__':
    main()
