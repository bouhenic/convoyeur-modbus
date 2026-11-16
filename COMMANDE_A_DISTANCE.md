# Commander le convoyeur depuis une machine distante

Le PC **192.168.5.51** fait tourner le simulateur (machine « lab »). Une autre machine du réseau lance le pupitre et se connecte à lui.

## 0. Copier le projet sur le PC lab

Depuis le Mac :

```bash
scp -r ~/code/convoyeur_modbus_v2 user@192.168.5.51:~/
```

Remplacer `user` par le nom d'utilisateur du PC distant.

Pour les mises à jour suivantes, `rsync` ne recopie que les fichiers modifiés :

```bash
rsync -avz --exclude '.venv' --exclude '__pycache__' ~/code/convoyeur_modbus_v2/ user@192.168.5.51:~/convoyeur_modbus_v2/
```

## 1. Ouvrir le pare-feu sur le PC lab (ufw)

```bash
sudo ufw allow 1502/tcp      # convoyeur
sudo ufw allow 5020/tcp      # seulement pour le TP convoyeur + robot
sudo ufw status
```

Pour n'autoriser qu'une seule machine :

```bash
sudo ufw allow from 192.168.5.X to any port 1502 proto tcp
```

Si ufw est désactivé : lancer `sudo ufw allow ssh` **avant** `sudo ufw enable`, sinon on risque de perdre l'accès SSH.

## 2. Lancer le simulateur sur le PC lab (192.168.5.51)

```bash
cd ~/convoyeur_modbus_v2
./lancer_tp.sh lab convoyeur
```

Ou à la main :

```bash
python3 simulateur_modbus.py --host 0.0.0.0 --sans-robot
```

> `--host 0.0.0.0` est **obligatoire**. Sans lui, le simulateur n'écoute que sur 127.0.0.1 et refuse les connexions des autres machines, même avec le port ouvert.

## 3. Lancer le pupitre sur la machine distante

```bash
cd ~/code/convoyeur_modbus_v2
./lancer_tp.sh pupitre convoyeur 192.168.5.51
```

Ou à la main :

```bash
python3 pupitre_pc.py --host 192.168.5.51
```

- Sur Mac : double-cliquer sur `TP_PUPITRE_MAC.command`. L'IP est retenue dans `serveur_lab.txt`.
- Sous Windows : `TP_PUPITRE_WINDOWS.bat`.
- Dans le pupitre, le champ **Serveur** en haut permet de changer d'IP sans relancer.

## 4. Si le pupitre affiche « Échec »

| Vérification | Commande / cause |
|---|---|
| Le port répond-il ? | `nc -zv 192.168.5.51 1502` (depuis la machine distante) |
| Pare-feu | `sudo ufw status` sur le PC lab |
| Simulateur lancé en mode lab ? | Il doit avoir été lancé avec `--host 0.0.0.0` |
| « machine injoignable » | Les deux machines ne sont pas sur le même réseau (Wi-Fi invité, isolation des clients…) |
| TP avec robot | Ouvrir aussi le port 5020 |

## Sécurité

Modbus TCP n'a **ni authentification ni chiffrement** : n'importe quel poste du réseau peut piloter le convoyeur. À utiliser uniquement sur le réseau du lab, jamais sur un réseau public.
