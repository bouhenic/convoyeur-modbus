#!/bin/bash
cd "$(dirname "$0")"
# Le python3 d'Apple (/usr/bin/python3) embarque Tk 8.5 : fenêtres blanches,
# textes invisibles. On cherche d'abord un Python avec Tk 8.6 ou plus récent.
for py in python3.14 python3.13 python3.12 python3.11 python3.10 python3 \
          /opt/homebrew/bin/python3 /usr/local/bin/python3 \
          /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import tkinter, sys; sys.exit(tkinter.TkVersion < 8.6)' 2>/dev/null; then
    exec "$py" demarrer.py
  fi
done
echo "Aucun Python avec Tkinter 8.6+ trouvé."
echo "Installez Python depuis https://www.python.org ou : brew install python-tk"
read -r -p "Appuyez sur Entrée pour fermer."
