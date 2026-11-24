# carbu-route

[![CI](https://github.com/remicartadepro/carbu-route/actions/workflows/ci.yml/badge.svg)](https://github.com/remicartadepro/carbu-route/actions/workflows/ci.yml)

Prix des carburants (E85 et autres) sur un trajet et sur une carte, à partir des données ouvertes de l'État.

Projet personnel d'apprentissage, hébergé dans un homelab : API REST en Python (FastAPI), carte Leaflet, conteneur Docker et chaîne CI/CD sur GitHub Actions.

## Fonctionnalités

- ✅ **Carte** : on se déplace et on zoome librement ; les stations de la zone affichée apparaissent, colorées du vert (la moins chère) au rouge.
- ✅ **Tous les carburants** : Gazole, SP95, SP98, E10, E85, GPLc (E85 par défaut) ; la bulle d'une station donne tous ses prix et leur date de mise à jour.
- ✅ **Liste** des 20 stations les moins chères de la zone.
- 🚧 **Trajet** : stations le long d'un itinéraire entre plusieurs adresses (étape 2).
- 🚧 **Release** : image publiée sur `ghcr.io` à chaque version (étape 3).

## Architecture

```
Navigateur ──▶ carbu-route (FastAPI, conteneur Docker)
   │                 │
   │                 └──▶ API « prix des carburants » (data.economie.gouv.fr)
   └──▶ fonds de carte OpenStreetMap

GitHub : push / PR ──▶ GitHub Actions (lint, tests, build et démarrage de l'image)
```

| Chemin | Rôle |
|---|---|
| `app/prix.py` | Interroge le flux officiel (filtre géographique côté serveur, pagination, cache de 10 min) et normalise les stations |
| `app/main.py` | API : `/api/stations`, `/api/carburants`, `/healthz` ; doc interactive sur `/docs` |
| `app/static/` | La page : carte Leaflet, sélecteur de carburant, liste |
| `tests/` | Tests pytest **hors ligne** (l'API externe est simulée) |
| `.github/workflows/ci.yml` | Lint (ruff), tests (pytest), construction et test de démarrage de l'image |

## Lancer

Avec Docker :

```bash
docker compose up -d --build
```

Puis ouvrir `http://ADRESSE-DE-LA-MACHINE:8080`. La géolocalisation (« Me localiser ») ne marche qu'en HTTPS, par exemple derrière un reverse proxy.

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

## Exemple d'appel

```bash
curl "http://localhost:8080/api/stations?lat=43.60&lon=1.44&rayon_km=10&carburant=e85"
```

Réponse : une liste de stations, les moins chères d'abord, chacune avec `adresse`, `ville`, `lat`, `lon` et `prix` (un objet par carburant : `prix` en €/L, `maj` = date de mise à jour).

## Données et licences

- Prix : [« Prix des carburants en France – Flux instantané – v2 »](https://www.data.gouv.fr/datasets/prix-des-carburants-en-france-flux-instantane-v2-amelioree), ministère de l'Économie, sous Licence Ouverte (Etalab). Mise à jour environ toutes les 10 minutes ; les prix sont déclarés par les stations.
- Cartes : © les contributeurs d'[OpenStreetMap](https://www.openstreetmap.org/copyright).
- Code : licence MIT.
