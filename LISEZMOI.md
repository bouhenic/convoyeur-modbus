# MODBUS LAB V2 — Convoyeur virtuel et pupitre de commande

**Objectif :** manipuler le protocole **Modbus TCP** sur un seul ordinateur, avant d'utiliser un ESP32.

Le logiciel propose deux vraies applications indépendantes, qui communiquent en **TCP/IP sur 127.0.0.1:1502** :

1. **Simulateur** (`simulateur_modbus.py`) : serveur Modbus TCP, machine virtuelle, capteurs, défauts, tableau des registres et journal réseau.
2. **Pupitre** (`pupitre_pc.py`) : client Modbus TCP, commandes, lecture périodique des capteurs, édition de PDU hexadécimales, décodeur détaillé des trames.

Les messages transitent réellement par la pile TCP/IP du système, même quand les deux applications tournent sur le même PC. Pas besoin d'ESP32, de réseau Wi-Fi ni de dépendance `pip`.

Le simulateur (« lab ») et les pupitres peuvent aussi tourner sur **deux machines différentes** du même réseau : voir **1 bis**.

## 1. Démarrage rapide

**Prérequis :** Python 3.9+ avec **Tkinter** (inclus dans les installations courantes de Python sous Windows/macOS). Linux : `python3-tk` si nécessaire. **macOS :** n'utilisez pas le `python3` d'Apple (`/usr/bin/python3`, Tk 8.5) : les fenêtres s'affichent blanches. Prenez Python de python.org ou de Homebrew (`brew install python-tk`) ; `LANCER_MAC.command` choisit automatiquement un Python avec Tk 8.6+.

Dans un terminal, placez-vous dans le dossier extrait, puis lancez :

```bash
python3 demarrer.py
```

Sous Windows, utilisez au besoin `py demarrer.py`.

**Quatre fenêtres s'ouvrent :** le simulateur du convoyeur (serveur, port **TCP 1502**, volontairement différent du port privilégié 502), la fenêtre du **robot Ned2 virtuel** (serveur, port **5020** comme le vrai robot), le **pupitre** du convoyeur et le **pupitre robot** (clients).

Pour ouvrir manuellement chaque fenêtre dans deux terminaux :

```bash
python3 simulateur_modbus.py
```

```bash
python3 pupitre_pc.py
```

```bash
python3 pupitre_robot.py
```

## 1 bis. Lab et pupitres sur deux machines

Une machine **LAB** fait tourner le simulateur, une ou plusieurs machines **PUPITRE** le pilotent à travers le réseau local. Les trames passent alors vraiment par le câble ou le Wi-Fi.

| Machine | macOS / Linux | Windows | Ligne de commande |
|---|---|---|---|
| **LAB** | `TP_LAB_MAC.command` | `TP_LAB_WINDOWS.bat` | `./lancer_tp.sh lab [convoyeur\|robot]` ou `python3 demarrer.py lab` |
| **PUPITRE** | `TP_PUPITRE_MAC.command` | `TP_PUPITRE_WINDOWS.bat` | `./lancer_tp.sh pupitre [convoyeur\|robot] [IP]` ou `python3 demarrer.py pupitre` |

1. **Sur la machine LAB**, lancez le lanceur *LAB* et choisissez le TP (convoyeur seul, ou convoyeur + robot). Le simulateur écoute sur **toutes les interfaces** (`--host 0.0.0.0`). La fenêtre du terminal et l'en-tête du simulateur affichent **l'adresse IP à communiquer**, par exemple `192.168.1.20`.
2. **Sur chaque machine PUPITRE**, lancez le lanceur *PUPITRE* : il demande le TP et l'IP de la machine lab, vérifie que les ports répondent, puis ouvre les pupitres. La dernière IP utilisée est retenue (fichier `serveur_lab.txt`) et proposée la fois suivante.
3. Dans chaque pupitre, le champ **Serveur** de l'en-tête permet de **changer d'adresse sans relancer** : saisir l'IP, puis **Connecter** (ou Entrée).

À la main, c'est équivalent à :

```bash
# Machine LAB
python3 simulateur_modbus.py --host 0.0.0.0          # ajouter --sans-robot pour le TP convoyeur seul
# Machine PUPITRE
python3 pupitre_pc.py --host 192.168.1.20
python3 pupitre_robot.py --host 192.168.1.20
```

Plusieurs pupitres peuvent piloter le même simulateur en même temps : ils voient tous la même machine.

**Si le pupitre affiche « Échec » :**

| Message | Cause probable |
|---|---|
| `refusée (simulateur arrêté ?)` | La machine lab répond, mais rien n'écoute sur le port : simulateur fermé, ou lancé sans le mode lab (il n'écoute alors que sur 127.0.0.1). |
| `pas de réponse (IP, pare-feu ?)` | Mauvaise IP, ou pare-feu de la machine lab qui bloque. |
| `machine injoignable` | Les deux machines ne sont pas sur le même réseau (Wi-Fi invité, isolation des clients…). |

**Pare-feu de la machine LAB :** au premier lancement, macOS ou Windows demande s'il faut autoriser Python à accepter des connexions entrantes : **acceptez, sur le réseau privé uniquement** (Windows : cochez « Réseaux privés », pas « Réseaux publics »). Ports utilisés : **TCP 1502** (convoyeur) et **TCP 5020** (robot).

**Sécurité :** Modbus TCP n'a **ni authentification ni chiffrement**. N'importe quel poste du réseau peut piloter le simulateur. Utilisez le mode lab seulement sur le réseau pédagogique, jamais sur un réseau public ou ouvert sur Internet.

**Latence :** le serveur du convoyeur coupe une connexion restée **12 s** sans requête. Avec la lecture automatique du pupitre, cela n'arrive pas, mais un Wi-Fi chargé peut produire des timeouts qu'on ne voit jamais en local. C'est l'occasion d'en parler.

## 2. Premier essai (sans ESP32)

1. Dans **Pupitre Modbus**, cliquez sur **MARCHE** ; le convoyeur doit commencer à avancer dans la fenêtre serveur.
2. Les cartons traversent successivement les capteurs virtuels **S1** et **S2**. Regardez la mise à jour des **Input Registers IR2, IR3** et du compteur **IR0**.
3. Saisissez **80** pour la vitesse, puis cliquez sur **Envoyer** : cela envoie une écriture de **Holding Register** avec le code fonction **06**.
4. Cliquez sur une opération du **journal des échanges**, puis sur **Décoder la trame**. Vous pourrez analyser le champ MBAP (7 octets) et la PDU (fonction, adresse et données).
5. Cliquez sur **ARRÊT**, puis observez les octets hexadécimaux envoyés.

## 3. Simuler une panne

1. Démarrez le convoyeur avec le pupitre.
2. Dans le **simulateur**, cliquez sur **Créer un bourrage**. Le moteur s'arrête, **IR4** prend la valeur **1** et **IR6** la valeur **2**.
3. Essayez de redémarrer depuis le pupitre : le serveur doit retourner **exception Modbus 04**, car la commande est impossible tant que le défaut n'est pas acquitté.
4. Dans le **simulateur**, cliquez sur **Libérer le bourrage**.
5. Dans le **pupitre**, cliquez sur **ACQUITTER UN DÉFAUT** : le coil impulsionnel à l'offset 1 est écrit avec la fonction **05**.
6. Vous pouvez maintenant redémarrer.

Un **arrêt d'urgence virtuel** permet d'étudier le même mécanisme de verrouillage. Ce bouton n'est **pas** un dispositif de sécurité pour des machines réelles.

## 4. Objectif de production

1. Dans le pupitre, saisir un objectif de **3 cartons**, puis **Envoyer**. Cette écriture concerne **HR1**.
2. Remettre le compteur à zéro, puis démarrer le convoyeur.
3. La production s'arrête après 3 cartons : l'état **IR6** vaut **3 = objectif atteint**.
4. Pour reprendre, choisir un objectif supérieur au compteur, ou remettre le compteur à zéro, puis envoyer MARCHE.

## 5. Table Modbus du simulateur

Les numéros ci-dessous sont les **offsets réellement encodés dans les trames** (base zéro). Chaque table Modbus possède ses propres offsets.

| Type | Offset | Accès | Code fonction | Signification |
|---|---:|---|---|---|
| Coil | 0 | L/E | 01 / 05 | Commande marche (1) ou arrêt (0) |
| Coil | 1 | E impulsion | 05 | Écrire 1 pour acquitter le défaut |
| Coil | 2 | E impulsion | 05 | Écrire 1 pour remettre le compteur à zéro |
| Discrete Input | 0 | L | 02 | Défaut détecté ou mémorisé (0/1) |
| Discrete Input | 1 | L | 02 | Objectif atteint (0/1) |
| Holding Register | 0 | L/E | 03 / 06 | Vitesse de 1 à 100 % |
| Holding Register | 1 | L/E | 03 / 06 | Objectif de 0 à 5000, 0 = infini |
| Input Register | 0 | L | 04 | Nombre de cartons, 16 bits |
| Input Register | 1 | L | 04 | État réel du moteur : 0/1 |
| Input Register | 2 | L | 04 | Capteur S1 (entrée) : 0/1 |
| Input Register | 3 | L | 04 | Capteur S2 (sortie) : 0/1 |
| Input Register | 4 | L | 04 | Code défaut : 0=aucun, 1=bourrage, 2=arrêt d'urgence virtuel |
| Input Register | 5 | L | 04 | Nombre de cartons sur le tapis |
| Input Register | 6 | L | 04 | État : 0=arrêt, 1=marche, 2=défaut, 3=objectif atteint |

Les adresses du **premier prototype** sont inchangées : coil 0, HR 0, IR 0 et IR 1. L'ancien programme ESP32 reste donc compatible. Les adresses ajoutées ne bloquent pas le matériel existant.

## 6. Exemples de PDU à saisir dans le pupitre

Le champ manuel attend **5 octets hexadécimaux**, sans l'en-tête MBAP. Le client construit lui-même l'en-tête TCP et affiche ensuite la requête et la réponse complètes.

La **requête et la réponse de la dernière PDU manuelle** s'affichent juste sous le champ (en vert si OK, en rouge si exception) ; le bouton **Décoder** à côté de **Envoyer PDU** les analyse octet par octet. Inutile de les chercher dans le journal.

Dans le **journal des échanges** :
- **Masquer les lectures automatiques** n'affiche plus que vos commandes et vos PDU manuelles ;
- cliquer sur une ligne **fige le défilement** (la case **Défilement auto** se décoche) ; la recocher pour suivre à nouveau les nouvelles trames.

| Requête PDU | Sens |
|---|---|
| `04 00 00 00 07` | Lire les 7 Input Registers à partir de IR0 |
| `03 00 00 00 02` | Lire vitesse et objectif |
| `01 00 00 00 01` | Lire l'état du coil Marche |
| `05 00 00 FF 00` | Écrire 1 dans le coil Marche |
| `05 00 00 00 00` | Écrire 0 dans le coil Marche |
| `06 00 00 00 50` | Régler la vitesse à 80 (0x0050) |
| `04 00 63 00 01` | Lire IR à l'offset 99, **exception Modbus 02** |
| `06 00 00 00 00` | Régler vitesse à 0, **exception Modbus 03** |
| `63 00 00 00 01` | Fonction inconnue 0x63, **exception Modbus 01** |

**Note :** Modbus TCP utilise l'en-tête MBAP, puis la PDU. La même PDU peut être encapsulée en RTU avec une adresse d'esclave et un CRC, mais la trame complète n'a pas la même structure.

## 7. Analyser dans Wireshark

Filtre d'affichage : `tcp.port == 1502` (ou `tcp.port == 5020` pour le robot). Sur un seul PC, sélectionnez l'interface **loopback** : `lo` (Linux), `lo0` (macOS), ou « Npcap Loopback Adapter » (Windows si Npcap est installé).

Avec le lab et les pupitres sur **deux machines** (section 1 bis), capturez sur l'**interface réseau réelle** (`en0` sur macOS, « Wi-Fi » ou « Ethernet » sous Windows, `wlan0`/`eth0` sous Linux), sur la machine lab ou sur un pupitre. Le filtre `ip.addr == 192.168.1.20 && tcp.port == 1502` isole les échanges avec la machine lab. Vous verrez aussi les vraies adresses IP et MAC des deux machines dans les en-têtes. Wireshark peut aussi nécessiter **Analyze → Decode As… → Modbus/TCP** pour le port 1502.

## 8. Tester automatiquement

```bash
python3 test_modbus.py
python3 test_robot.py
```

`test_robot.py` vérifie la cinématique du Ned2, les adresses Niryo, l'encodage float32, les mouvements bloquants ou non, IR 120, la prise d'un carton et le programme embarqué. Les tests du convoyeur couvrent la lecture des registres et coils, les commandes, le compteur, la vitesse, les objectifs, les pannes, le décodage des exceptions et les PDU brutes.

## 9. Réutiliser un ESP32 plus tard

Le programme `esp32_client_modbus.ino` est issu de la première version. Il commande marche/arrêt sur coil 0 et lit le compteur sur IR0.

1. Arduino IDE : bibliothèque `modbus-esp8266` d'Alexander Emelianov (compatible ESP32).
2. Adapter le SSID/mot de passe et l'adresse IP du PC dans le `.ino`.
3. **Lancer le serveur** en mode lab (`TP_LAB_MAC.command`, `TP_LAB_WINDOWS.bat` ou `python3 simulateur_modbus.py --host 0.0.0.0`) : par défaut le laboratoire reste limité à 127.0.0.1, donc inaccessible aux appareils du réseau local.
4. Autoriser TCP **1502** dans le pare-feu, **uniquement sur le réseau privé pédagogique**.
5. Brancher deux boutons entre GPIO 18/GND et GPIO 19/GND, `INPUT_PULLUP` activés.

## 10. Robot Niryo Ned2 virtuel (port 5020)

Le simulateur contient un **bras Niryo Ned2 virtuel** placé en bout de convoyeur, avec deux bacs de dépose. Il expose **la même table Modbus que le firmware Niryo** (paquet `niryo_robot_modbus` du dépôt `NiryoRobotics/ned_ros`) : ce qui est appris ici fonctionne avec un vrai Ned2.

- Cinématique tirée de l'URDF officiel du Ned2 (6 axes, butées réelles).
- Pince « Gripper 1 » (ID outil 11), sans caméra ni convoyeur Niryo.
- `python3 pupitre_robot.py --host <IP du robot>` pilote un **vrai** Ned2 (port 5020).

### Les réels Niryo : float32 sur deux registres

Angles (radians), positions (mètres) et tensions sont des **float32 IEEE 754** répartis sur **deux registres de 16 bits**, mot de poids fort en premier.
Exemple : `0,5 rad` → `3F 00 00 00` → registres `0x3F00` puis `0x0000`. Le bouton **Décoder la trame** du pupitre robot affiche cette conversion.

Écrire un float demande la fonction **16** (*Write Multiple Registers*) : avec la fonction 06, on n'envoie qu'une moitié du nombre et **le robot ignore l'écriture sans signaler d'erreur**.

### Table utile (adresses du firmware, base 0)

| Type | Adresse | Accès | Signification |
|---|---:|---|---|
| Coil | 0–3 | L/E | Sorties TOR DO1–DO4 |
| Coil | 51 | L/E | Pince : 1 = fermer (saisir), 0 = ouvrir |
| Coil | 113 | L/E | Lecture : robot en mouvement · écrire 1 = lancer le mouvement, 0 = arrêter |
| Coil | 117 | L/E | Collision détectée · écrire 0 pour l'effacer |
| Coil | 118 | L/E | Mouvements bloquants (1 par défaut) |
| Coil | 200–299 | L/E | Zone utilisateur (bits) |
| Discrete Input | 0–4 | L | Entrées TOR DI1–DI5 (**DI1 = capteur S2 du convoyeur**) |
| Discrete Input | 51 | L | Commande en cours d'exécution |
| Holding Register | 50–61 | L/E | Cible articulaire J1–J6 (6 float32, rad) |
| Holding Register | 62–73 | L/E | Cible en pose x, y, z (m), roll, pitch, yaw (rad) |
| Holding Register | 74 | L/E | Type de mouvement : 0 = MOVE_J, 1 = MOVE_P, 2 = MOVE_L |
| Holding Register | 142 | L/E | Vitesse du bras (%) |
| Holding Register | 200–399 / 400–499 | L/E | Zone utilisateur float32 / entiers |
| Input Register | 50–61 | L | Position articulaire J1–J6 (float32, rad) |
| Input Register | 62–73 | L | Pose de l'outil (float32) |
| Input Register | 120 | L | Résultat de la dernière commande : 0 = OK, 1 = erreur Modbus, 2 = erreur robot |
| Input Register | 121 | L | ID de l'outil (11 = Gripper 1) |

Les autres adresses du firmware (TCP, réglages de pince, vision, versions…) existent aussi. Une adresse **non attribuée** renvoie l'**exception 02** : par exemple coil 4 (le Ned2 n'a que 4 sorties) ou HR 87 (pas de convoyeur Niryo branché).

### Faire bouger le robot

1. **FC16** : écrire la cible dans HR 50–61 (articulaire) ou HR 62–73 (pose).
2. **FC06** : HR 74 = type de mouvement.
3. **FC05** : coil 113 = 1.
4. **FC04** : lire IR 120.

**Attention :** un mouvement impossible (pose hors d'atteinte, butée, collision non effacée, arrêt d'urgence) ne renvoie **pas** d'exception Modbus. La réponse est normale et seul **IR 120 = 2** signale le refus. Il faut donc toujours lire IR 120 après une commande.

Avec la coil 118 à 1 (valeur par défaut), la réponse à l'écriture de la coil 113 n'arrive **qu'à la fin du mouvement**. Le pupitre robot utilise donc une seconde connexion pour continuer à lire l'état : **DI 51** passe à 1 pendant l'attente.

### La cellule convoyeur + robot

Dans la fenêtre du robot, cocher **Poste robot** : les cartons s'arrêtent en bout de tapis, le capteur **S2** est câblé sur l'entrée **DI1** du robot, et un carton n'est compté (IR0 du convoyeur) que lorsque le robot l'a saisi. Quatre cartons accumulés provoquent un **bourrage**. En mode poste robot, un carton arrive toutes les 5 s.

Le **programme embarqué** (bouton *Lancer*, comme un programme démarré depuis Niryo Studio) attend un carton sur DI1, le saisit et le dépose dans un bac. Il communique par la zone utilisateur Niryo :

| Adresse | Rôle (convention de ce TP) |
|---|---|
| HR 400 | Bac de dépose : 0 = A, 1 = B |
| HR 401 | Nombre de pièces déposées (écrit par le programme) |
| Coil 200 | 1 = pause du programme |

### Exercices proposés

1. Lire les 6 angles (`04 00 32 00 0C`), puis les convertir en degrés à partir des octets.
2. Faire une prise manuelle avec le pupitre robot : *au-dessus prise* (MOVE_P), *prise* (MOVE_L), fermer la pince, remonter, *bac B*, ouvrir.
3. Envoyer une pose hors d'atteinte : observer la réponse Modbus normale et IR 120 = 2.
4. Écrire HR 50 avec FC06 et constater que rien ne change.
5. Lancer le programme embarqué avec le convoyeur, puis baisser HR 142 à 40 % : le robot ne suit plus la cadence et le bourrage apparaît.

## Limites

Il s'agit d'un **simulateur pédagogique** écrit en Python standard. Il ne prend en charge qu'une partie du protocole Modbus : codes 01 à 06 et Unit ID 1 pour le convoyeur ; codes 01 à 06, 15 et 16, tout Unit ID, pour le robot. Le robot virtuel reproduit la table et les comportements Modbus du firmware Niryo, mais pas sa dynamique exacte (vitesses, trajectoires et collisions sont simplifiées). Il ne doit pas être utilisé comme automate de sécurité, ni exposé directement à Internet. Le capteur, le convoyeur, les cartons et les défauts sont **entièrement virtuels**.
