# carbu-route

[![CI](https://github.com/remicartadepro/carbu-route/actions/workflows/ci.yml/badge.svg)](https://github.com/remicartadepro/carbu-route/actions/workflows/ci.yml)

Prix des carburants (E85 et autres) sur un trajet et sur une carte, à partir des données ouvertes de l'État.

Projet personnel d'apprentissage, hébergé dans un homelab : API REST en Python (FastAPI), carte Leaflet, conteneur Docker et chaîne CI/CD sur GitHub Actions.

## Fonctionnalités

- ✅ **Carte** : on se déplace et on zoome librement ; les stations de la zone affichée apparaissent, colorées du vert (la moins chère) au rouge.
- ✅ **Tous les carburants** : Gazole, SP95, SP98, E10, E85, GPLc (E85 par défaut) ; la bulle d'une station donne tous ses prix et leur date de mise à jour.
- ✅ **Liste** des 20 stations les moins chères de la zone.
- ✅ **Prix périmés** : un prix de plus de 15 jours est affiché en gris et classé après les prix frais.
- ✅ **Trajet** : départ, jusqu'à 4 étapes et arrivée ; le tracé s'affiche, avec les stations à moins de 1, 2, 5 ou 10 km de la route, leur position (« au km 12 du trajet ») et leur écart à la route.
- ✅ **Release** : à chaque version (tag `vX.Y.Z`), l'image est testée, construite et publiée sur `ghcr.io`.

## Architecture

```
Navigateur ──▶ carbu-route (FastAPI, conteneur Docker)
   │                 │
   │                 ├──▶ API « prix des carburants » (data.economie.gouv.fr)
   │                 └──▶ Géoplateforme IGN : géocodage et itinéraire (data.geopf.fr)
   └──▶ fonds de carte OpenStreetMap

GitHub : PR ──▶ CI (lint, tests, build et démarrage de l'image)
        release vX.Y.Z ──▶ CI, puis image publiée sur ghcr.io ◀── docker compose pull (serveur)
```

Le déploiement est en **pull** : c'est le serveur qui va chercher l'image, GitHub n'a aucun accès entrant vers lui.

| Chemin | Rôle |
|---|---|
| `app/prix.py` | Interroge le flux officiel (filtre géographique côté serveur, pagination, cache de 10 min) et normalise les stations |
| `app/trajet.py` | Adresses → coordonnées, itinéraire, puis stations proches du tracé (points de contrôle tous les 500 m, projection plane locale) |
| `app/main.py` | API : `/api/stations`, `POST /api/trajet`, `/api/carburants`, `/healthz` ; doc interactive sur `/docs` |
| `app/static/` | La page : carte Leaflet, sélecteur de carburant, liste |
| `tests/` | Tests pytest **hors ligne** (l'API externe est simulée) |
| `.github/workflows/ci.yml` | Lint (ruff), tests (pytest), construction et test de démarrage de l'image |
| `.github/workflows/release.yml` | Sur un tag `vX.Y.Z` : relance la CI, puis publie l'image (`X.Y.Z`, `X.Y`, `latest`) sur GHCR |
| `compose.yaml` | Déploiement de l'image publiée, version et adresse d'écoute lues dans `.env` (modèle : `.env.exemple`) |

## Lancer

Avec l'image publiée (dans un dossier contenant `compose.yaml`) :

```bash
cp .env.exemple .env
```

```bash
docker compose pull && docker compose up -d
```

Puis ouvrir `http://127.0.0.1:8080` (adresse d'écoute réglable par `CARBU_BIND` dans `.env`). La géolocalisation (« Me localiser ») ne marche qu'en HTTPS, par exemple derrière un reverse proxy. `/healthz` renvoie la version qui tourne.

Mettre à jour : changer `CARBU_TAG` dans `.env`, puis relancer la même commande.

En développement :

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

```bash
.venv/bin/uvicorn app.main:app --reload --port 8080
```

```bash
.venv/bin/ruff check . && .venv/bin/pytest -q
```

Construire l'image depuis le code local :

```bash
CARBU_TAG=dev docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

## Publier une version

1. Fusionner les changements dans `main` (CI verte).
2. Sur GitHub : *Releases → Draft a new release*, créer le tag `vX.Y.Z` (versionnage sémantique), décrire les changements, *Publish release*.
3. Le workflow *Release* relance les vérifications puis publie `ghcr.io/remicartadepro/carbu-route:X.Y.Z`.

## Exemple d'appel

```bash
curl "http://localhost:8080/api/stations?lat=43.60&lon=1.44&rayon_km=10&carburant=e85"
```

```bash
curl -X POST http://localhost:8080/api/trajet -H "Content-Type: application/json" -d '{"adresses": ["Toulouse", "Carcassonne"], "carburant": "e85", "detour_km": 2}'
```

Réponse de `/api/stations` : une liste de stations, les moins chères d'abord, chacune avec `adresse`, `ville`, `lat`, `lon` et `prix` (un objet par carburant : `prix` en €/L, `maj` = date de mise à jour).

## Données et licences

- Prix : [« Prix des carburants en France – Flux instantané – v2 »](https://www.data.gouv.fr/datasets/prix-des-carburants-en-france-flux-instantane-v2-amelioree), ministère de l'Économie, sous Licence Ouverte (Etalab). Mise à jour environ toutes les 10 minutes ; les prix sont déclarés par les stations.
- Géocodage et itinéraire : services de la [Géoplateforme de l'IGN](https://www.data.gouv.fr/dataservices/api-geoplateforme-calcul-ditineraire) (données BD TOPO et Base Adresse Nationale), publics et sans clé.
- Cartes : © les contributeurs d'[OpenStreetMap](https://www.openstreetmap.org/copyright).
- Code : licence MIT.
