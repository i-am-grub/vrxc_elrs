# VRxC ELRS Web Bridge

Plugin RotorHazard : le **timer backpack ELRS** (ESP32/ESP8266) est branché en USB sur un **PC près du pilote**, et non sur le Raspberry Pi du timer. Le PC y accède depuis Chrome (Web Serial).

```
RotorHazard (Pi) --wifi/socket.io--> Chrome (PC) --USB--> ESP --ESP-NOW--> backpack goggles
```

Basé sur [VRxC_ELRS](https://github.com/i-am-grub/VRxC_ELRS) (GPL-3.0) : toute la logique OSD (départ, tours, écarts, résultats, bind phrase par pilote) est conservée. Seul le transport change : un type de connexion **WEB** envoie les trames MSP au navigateur au lieu d'un port série local.

## Installation

1. Copier `custom_plugins/vrxc_elrs_web` dans `custom_plugins/` de RotorHazard, puis redémarrer le serveur.
2. **Ne pas installer en même temps `vrxc_elrs`** (mêmes noms d'options et d'attributs pilote).
3. Flasher l'ESP avec le firmware *Timer Backpack* d'[ExpressLRS Backpack](https://github.com/ExpressLRS/Backpack), comme pour VRxC_ELRS.

## Utilisation

1. **Une seule fois par PC** : Chrome ne donne accès à Web Serial qu'aux pages sécurisées, or RotorHazard est en `http`.
   Ouvrir `chrome://flags/#unsafely-treat-insecure-origin-as-secure`, y ajouter `http://<ip-du-pi>:5000`, passer le réglage sur *Enabled*, relancer Chrome.
2. Dans RotorHazard, *Settings → ELRS Backpack General Settings* : type de connexion **WEB**.
3. Sur le PC, ouvrir `http://<ip-du-pi>:5000/elrs_web` dans Chrome/Edge, brancher l'ESP, cliquer **Connect ESP** et choisir le port. Aux visites suivantes, la page se reconnecte seule.
4. Le plugin se connecte automatiquement dès que l'ESP est ouvert. Le reste (bind phrase pilote, « Enable ELRS OSD », messages) se règle comme dans VRxC_ELRS.

Garder l'onglet ouvert pendant l'événement. Un seul PC/onglet bridge à la fois.

## Changement de canal depuis le backpack de la radio

Quand un pilote change son canal VTX depuis sa radio, le backpack de la radio diffuse un `MSP_SET_VTX_CONFIG`. Si le firmware de l'ESP timer remonte ce paquet par l'USB, le plugin applique la fréquence au node choisi.

- Réglage : *Settings → ELRS Backpack General Settings → Node for Backpack Channel Changes* (0 = désactivé).
- Le paquet peut contenir un index de table VTX (bandes A B E F R L, 8 canaux) ou une fréquence en MHz. Les fréquences hors table sont appliquées sans bande ni canal.
- Ignoré pendant une manche (staging ou course), pour ne pas décaler un node en plein chronométrage.
- Le firmware **Race Timer officiel ne remonte pas** ce paquet : il faut un firmware ESP modifié.

## Limites connues

- Chrome/Edge uniquement (pas de Web Serial dans Firefox/Safari).
- Pas de test sur matériel réel à ce stade : seul le transport serveur a été testé (stubs RotorHazard).
