"""Lecture du flux officiel des prix des carburants (DGCCRF, données ouvertes).

Source : jeu « prix-des-carburants-en-france-flux-instantane-v2 » sur
data.economie.gouv.fr (API Explore v2.1, sans clé, mis à jour toutes les
10 minutes environ). Une ligne = une station, une colonne par carburant
(`e85_prix`, `e85_maj`, …).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

URL_API = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "prix-des-carburants-en-france-flux-instantane-v2/records"
)

# Codes des carburants tels qu'ils apparaissent dans les noms de colonnes.
CARBURANTS: dict[str, str] = {
    "gazole": "Gazole",
    "sp95": "SP95",
    "sp98": "SP98",
    "e10": "E10",
    "e85": "E85",
    "gplc": "GPLc",
}

RAYON_MAX_KM = 50
TAILLE_PAGE = 100  # maximum accepté par l'API Explore pour /records
DUREE_CACHE_S = 600  # le flux ne bouge pas plus vite que toutes les 10 min


@dataclass
class Station:
    id: str
    adresse: str
    ville: str
    cp: str
    lat: float
    lon: float
    prix: dict[str, dict[str, Any]] = field(default_factory=dict)

    def prix_de(self, carburant: str) -> float | None:
        info = self.prix.get(carburant)
        return info["prix"] if info else None


def _coordonnee(valeur: Any, limite: float) -> float | None:
    """Convertit une coordonnée ; l'ancien format les multiplie par 100 000."""
    if valeur in (None, ""):
        return None
    nombre = float(valeur)
    if abs(nombre) > limite:
        nombre /= 100_000
    return nombre


def normaliser(enregistrement: dict[str, Any]) -> Station | None:
    """Transforme une ligne brute de l'API en Station (None si inutilisable)."""
    geom = enregistrement.get("geom") or {}
    lat = geom.get("lat")
    lon = geom.get("lon")
    if lat is None or lon is None:
        lat = _coordonnee(enregistrement.get("latitude"), 90)
        lon = _coordonnee(enregistrement.get("longitude"), 180)
    if lat is None or lon is None:
        return None

    prix: dict[str, dict[str, Any]] = {}
    for code in CARBURANTS:
        valeur = enregistrement.get(f"{code}_prix")
        if valeur is None:
            continue
        prix[code] = {"prix": float(valeur), "maj": enregistrement.get(f"{code}_maj")}

    return Station(
        id=str(enregistrement.get("id", "")),
        adresse=str(enregistrement.get("adresse") or ""),
        ville=str(enregistrement.get("ville") or ""),
        cp=str(enregistrement.get("cp") or ""),
        lat=float(lat),
        lon=float(lon),
        prix=prix,
    )


def construire_filtre(lat: float, lon: float, rayon_km: float, carburant: str) -> str:
    """Clause `where` (langage ODSQL) : stations dans le rayon qui vendent ce carburant."""
    if carburant not in CARBURANTS:
        raise ValueError(f"carburant inconnu : {carburant}")
    rayon = min(max(rayon_km, 0.5), RAYON_MAX_KM)
    return (
        f"within_distance(geom, geom'POINT({lon} {lat})', {rayon}km) "
        f"and {carburant}_prix is not null"
    )


def trier_par_prix(stations: list[Station], carburant: str) -> list[Station]:
    """Les moins chères d'abord ; une station sans ce carburant passe à la fin."""
    return sorted(
        stations,
        key=lambda s: (s.prix_de(carburant) is None, s.prix_de(carburant) or 0.0),
    )


class ClientPrix:
    """Interroge l'API et garde les réponses en cache quelques minutes."""

    def __init__(self, client: httpx.Client | None = None, duree_cache_s: int = DUREE_CACHE_S):
        self._client = client or httpx.Client(timeout=20.0)
        self._duree_cache_s = duree_cache_s
        self._cache: dict[tuple, tuple[float, list[Station]]] = {}

    def stations_autour(
        self, lat: float, lon: float, rayon_km: float, carburant: str
    ) -> list[Station]:
        cle = (round(lat, 3), round(lon, 3), round(rayon_km, 1), carburant)
        en_cache = self._cache.get(cle)
        if en_cache and time.monotonic() - en_cache[0] < self._duree_cache_s:
            return en_cache[1]

        filtre = construire_filtre(lat, lon, rayon_km, carburant)
        stations: list[Station] = []
        decalage = 0
        while True:
            reponse = self._client.get(
                URL_API,
                params={"where": filtre, "limit": TAILLE_PAGE, "offset": decalage},
            )
            reponse.raise_for_status()
            resultats = reponse.json().get("results", [])
            stations.extend(s for s in map(normaliser, resultats) if s is not None)
            if len(resultats) < TAILLE_PAGE:
                break
            decalage += TAILLE_PAGE

        stations = trier_par_prix(stations, carburant)
        self._cache[cle] = (time.monotonic(), stations)
        return stations
