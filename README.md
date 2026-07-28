# Govee Charts (BLE)

Collecte température / humidité des thermomètres Govee à portée Bluetooth LE,
stocke l’historique en SQLite, et affiche des graphiques dans une page HTML.

Plusieurs instances peuvent se fédérer sur le réseau local : chaque nœud scanne
près de lui et pousse ses mesures vers les autres.

## Capteurs supportés

- **H5075** / H5072 (manufacturer ID `0xEC88`)
- **H5179** (manufacturer ID `0x8801`)

Découverte automatique : tout appareil Govee émettant ces données apparaît sans configuration.

## Prérequis

- Python 3.11+
- Adaptateur Bluetooth Linux (`hci0`) à portée des capteurs (sauf nœud hub sans scan)
- Optionnel : 2ᵉ dongle USB (`hci1`) plus proche des capteurs éloignés

## Installation

```bash
cd ~/govee-charts
make install
# optionnel : éditer config.toml (labels, port, rétention, federation)
```

## Usage

```bash
make discover   # scan 30 s, liste les Govee détectés
make run        # collector + serveur web
```

Ouvrir [http://127.0.0.1:8080](http://127.0.0.1:8080).

## Fédération (plusieurs machines)

Sur chaque machine : installer le projet, puis croiser les URLs dans `[federation]` :

```toml
[federation]
node_id = "cave"          # unique par machine
token = "un-secret-partage"
peers = ["http://192.168.1.10:8080"]   # l’autre instance
```

Sur l’autre nœud, `peers` pointe vers celui-ci. Les mesures BLE **locales** sont
poussées vers les pairs ; les données reçues ne sont pas renvoyées (pas de boucle).

Hub sans Bluetooth (UI centrale seulement) :

```toml
[scanner]
enabled = false
```

## Configuration

Voir `config.example.toml` :

- `scanner.enabled` — activer/désactiver le scan BLE local
- `scanner.sample_interval` — intervalle min entre deux points enregistrés (défaut 60 s)
- `scanner.retention_days` — durée de conservation (défaut 30 j)
- `scanner.adapters` — liste d’adaptateurs BlueZ (`["hci0", "hci1"]`)
- `federation.peers` — URLs des autres instances
- `federation.token` — secret partagé pour `POST /api/ingest`
- `[labels]` — noms amicaux par adresse MAC

## API

- `GET /api/devices` — appareils connus + dernière mesure
- `GET /api/history?address=…&hours=24` — série temporelle
- `POST /api/ingest` — réception des mesures d’un pair (header `X-Govee-Token`)
- `GET /api/health` — santé + `node_id`

## Notes

- Soft-blocked : `rfkill unblock bluetooth`
- Pas d’API cloud Govee — BLE uniquement
