#!/bin/bash
# Lance la configuration demandée pour le TP, sans doublon.
#
# Tout sur ce PC (simulateur limité à 127.0.0.1) :
#   ./lancer_tp.sh convoyeur            → simulateur sans robot + pupitre PC
#   ./lancer_tp.sh robot                → simulateur avec robot + pupitre PC + pupitre robot
#
# Lab et pupitres sur des machines différentes :
#   ./lancer_tp.sh lab [convoyeur|robot]             → simulateur seul, ouvert au réseau (0.0.0.0)
#   ./lancer_tp.sh pupitre [convoyeur|robot] [IP]    → pupitres seuls, vers le simulateur distant
# Sans convoyeur|robot ni IP, le script les demande (l'IP précédente est proposée).
#
# Un programme déjà ouvert dans la bonne configuration n'est pas relancé.
# Un simulateur ouvert dans l'autre configuration est arrêté puis relancé.
cd "$(dirname "$0")"
PORT=1502
PORT_ROBOT=5020
MEMOIRE="serveur_lab.txt"
ROLE="$1"

pause_fin() { read -r -p "Appuyez sur Entrée pour fermer."; }
usage() {
  echo "Usage : $0 convoyeur|robot"
  echo "        $0 lab [convoyeur|robot]"
  echo "        $0 pupitre [convoyeur|robot] [IP du simulateur]"
  pause_fin; exit 1
}

demander_mode() {
  echo "Quel TP ?"
  echo "  1) Convoyeur seul"
  echo "  2) Convoyeur + robot Ned2"
  read -r -p "Choix [1] : " choix
  case "$choix" in
    2|robot) MODE=robot ;;
    ""|1|convoyeur) MODE=convoyeur ;;
    *) echo "Choix invalide."; pause_fin; exit 1 ;;
  esac
}

case "$ROLE" in
  convoyeur|robot) MODE="$ROLE"; ROLE=local ;;
  lab|pupitre)
    MODE="$2"
    case "$MODE" in
      convoyeur|robot) ;;
      "") demander_mode ;;
      *) usage ;;
    esac ;;
  *) usage ;;
esac

# Un Python avec Tk 8.6+ (le python3 d'Apple donne des fenêtres blanches).
PY=""
for py in python3.14 python3.13 python3.12 python3.11 python3.10 python3 \
          /opt/homebrew/bin/python3 /usr/local/bin/python3 \
          /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import tkinter, sys; sys.exit(tkinter.TkVersion < 8.6)' 2>/dev/null; then
    PY="$py"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Aucun Python avec Tkinter 8.6+ trouvé."
  if [ "$(uname)" = Darwin ]; then
    echo "Installez Python depuis https://www.python.org ou : brew install python-tk"
  else
    echo "Installez Tkinter : sudo apt install python3-tk"
  fi
  pause_fin; exit 1
fi

# Test d'un port TCP avec un délai court : /dev/tcp vers une IP injoignable
# peut bloquer plus d'une minute.
port_ouvert() {  # port_ouvert HÔTE PORT
  "$PY" -c 'import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1.5).close()
except OSError:
    sys.exit(1)' "$1" "$2" 2>/dev/null
}
tourne() { pgrep -f "$1" >/dev/null; }
lancer() { nohup "$PY" "$@" >/dev/null 2>&1 & }

# ---------------------------------------------------------------------------
# Machine PUPITRE : pas de simulateur, seulement les clients.
# ---------------------------------------------------------------------------
if [ "$ROLE" = pupitre ]; then
  HOTE="$3"
  if [ -z "$HOTE" ]; then
    DEFAUT="$(cat "$MEMOIRE" 2>/dev/null | head -n 1)"
    if [ -n "$DEFAUT" ]; then
      read -r -p "Adresse IP de la machine lab [$DEFAUT] : " HOTE
      HOTE="${HOTE:-$DEFAUT}"
    else
      read -r -p "Adresse IP de la machine lab (affichée dans son terminal) : " HOTE
    fi
  fi
  HOTE="$(echo "$HOTE" | tr -d '[:space:]')"
  if [ -z "$HOTE" ]; then
    echo "✖ Aucune adresse saisie."; pause_fin; exit 1
  fi
  case "$HOTE" in 127.*|localhost) ;; *) echo "$HOTE" > "$MEMOIRE" ;; esac

  echo "=== Pupitres → simulateur $HOTE ($MODE) ==="
  ports="$PORT"; [ "$MODE" = robot ] && ports="$PORT $PORT_ROBOT"
  for p in $ports; do
    if port_ouvert "$HOTE" "$p"; then
      echo "✔ $HOTE:$p répond."
    else
      echo "⚠ $HOTE:$p ne répond pas. Vérifiez sur la machine lab :"
      echo "    - le simulateur est lancé en mode lab (TP_LAB_MAC.command ou : ./lancer_tp.sh lab) ;"
      echo "    - le pare-feu autorise Python (ports TCP $PORT et $PORT_ROBOT) ;"
      echo "    - les deux machines sont sur le même réseau, et l'IP est la bonne."
      echo "  Les pupitres s'ouvrent quand même : ils réessaient seuls, et l'adresse"
      echo "  se corrige dans le champ « Serveur » de leur en-tête."
    fi
  done

  if [ "$MODE" = convoyeur ] && tourne "pupitre_robot.py"; then
    echo "■ Fermeture du pupitre robot…"
    pkill -f "pupitre_robot.py"
  fi
  if tourne "pupitre_pc.py"; then
    echo "✔ Pupitre convoyeur déjà lancé (changez l'adresse dans son champ « Serveur »)."
  else
    echo "▶ Lancement du pupitre convoyeur…"
    lancer pupitre_pc.py --host "$HOTE"
  fi
  if [ "$MODE" = robot ]; then
    if tourne "pupitre_robot.py"; then
      echo "✔ Pupitre robot déjà lancé (changez l'adresse dans son champ « Serveur »)."
    else
      echo "▶ Lancement du pupitre robot…"
      lancer pupitre_robot.py --host "$HOTE"
    fi
  fi
  echo "Terminé. Vous pouvez fermer cette fenêtre."
  exit 0
fi

# ---------------------------------------------------------------------------
# Simulateur (machine LAB, ou tout sur ce PC).
# ---------------------------------------------------------------------------
SIM_ARGS=()
[ "$ROLE" = lab ] && SIM_ARGS+=(--host 0.0.0.0)
[ "$MODE" = convoyeur ] && SIM_ARGS+=(--sans-robot)

# Le simulateur qui tourne est-il dans la bonne configuration ?
# En local, un simulateur ouvert au réseau convient aussi (il accepte 127.0.0.1).
sim_sans_robot() { tourne "simulateur_modbus.py.*--sans-robot"; }
sim_reseau() { tourne "simulateur_modbus.py.*--host 0\.0\.0\.0"; }
sim_bon_mode() {
  tourne "simulateur_modbus.py" || return 1
  if [ "$MODE" = convoyeur ]; then sim_sans_robot || return 1; else ! sim_sans_robot || return 1; fi
  if [ "$ROLE" = lab ]; then sim_reseau || return 1; fi
  return 0
}

case "$ROLE:$MODE" in
  local:convoyeur) echo "=== TP convoyeur seul ===" ;;
  local:robot)     echo "=== TP convoyeur + robot ===" ;;
  lab:convoyeur)   echo "=== Machine LAB : convoyeur seul, ouvert au réseau ===" ;;
  lab:robot)       echo "=== Machine LAB : convoyeur + robot, ouvert au réseau ===" ;;
esac
if [ "$MODE" = convoyeur ] && [ "$ROLE" = local ] && tourne "pupitre_robot.py"; then
  echo "■ Fermeture du pupitre robot…"
  pkill -f "pupitre_robot.py"
fi

if tourne "simulateur_modbus.py" && ! sim_bon_mode; then
  echo "■ Simulateur dans une autre configuration : arrêt pour le relancer…"
  pkill -f "simulateur_modbus.py"
  for _ in $(seq 1 25); do port_ouvert 127.0.0.1 "$PORT" || break; sleep 0.2; done
fi
if sim_bon_mode; then
  echo "✔ Simulateur déjà lancé (port $PORT)."
elif port_ouvert 127.0.0.1 "$PORT"; then
  echo "✖ Le port $PORT est occupé par un autre programme."
  pause_fin; exit 1
else
  echo "▶ Lancement du simulateur…"
  lancer simulateur_modbus.py "${SIM_ARGS[@]}"
  for _ in $(seq 1 30); do port_ouvert 127.0.0.1 "$PORT" && break; sleep 0.2; done
  if ! port_ouvert 127.0.0.1 "$PORT"; then
    echo "✖ Le simulateur n'écoute pas sur le port $PORT."
    pause_fin; exit 1
  fi
fi

if [ "$ROLE" = lab ]; then
  IP="$("$PY" -c 'from modbus_core import local_ipv4; print(local_ipv4())' 2>/dev/null)"
  echo
  echo "  Adresse à donner aux pupitres :  ${IP:-IP de ce PC}"
  echo "  (port $PORT convoyeur$([ "$MODE" = robot ] && echo ", $PORT_ROBOT robot"))"
  echo
  echo "  Sur chaque machine pupitre : TP_PUPITRE_MAC.command (ou TP_PUPITRE_WINDOWS.bat)."
  echo "  Si le système demande d'accepter les connexions entrantes pour Python :"
  echo "  acceptez, sur le réseau privé du TP uniquement."
  echo "Terminé. Vous pouvez fermer cette fenêtre."
  exit 0
fi

# 2. Pupitre PC (convoyeur)
if tourne "pupitre_pc.py"; then
  echo "✔ Pupitre convoyeur déjà lancé."
else
  echo "▶ Lancement du pupitre convoyeur…"
  lancer pupitre_pc.py
fi

# 3. Pupitre robot (TP robot seulement)
if [ "$MODE" = robot ]; then
  if tourne "pupitre_robot.py"; then
    echo "✔ Pupitre robot déjà lancé."
  else
    echo "▶ Lancement du pupitre robot…"
    lancer pupitre_robot.py
  fi
fi

echo "Terminé. Vous pouvez fermer cette fenêtre."
