"""Itinéraire entre plusieurs adresses et stations le long du tracé.

Services de la Géoplateforme de l'IGN, publics et sans clé :
- géocodage (adresse → coordonnées) : https://data.geopf.fr/geocodage/search
- itinéraire : https://data.geopf.fr/navigation/itineraire (ressource `bdtopo-osrm`)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import httpx

from app.prix import ClientPrix, Station, trier_par_prix

URL_GEOCODAGE = "https://data.geopf.fr/geocodage/search"
URL_ITINERAIRE = "https://data.geopf.fr/navigation/itineraire"

RAYON_TERRE_KM = 6371.0
PAS_KM = 0.5  # espacement des points de contrôle le long du tracé
DETOUR_MAX_KM = 10.0


class AdresseIntrouvable(ValueError):
    """Le géocodeur n'a rien trouvé pour une adresse."""


@dataclass
class Etape:
    adresse: str
    libelle: str
    lat: float
    lon: float


@dataclass
class StationSurTrajet:
    station: Station
    ecart_km: float  # distance à vol d'oiseau entre la station et le tracé
    km_depuis_depart: float  # position le long du trajet


@dataclass
class Trajet:
    etapes: list[Etape]
    distance_km: float
    duree_min: float
    trace: list[tuple[float, float]]  # (lat, lon)
    stations: list[StationSurTrajet] = field(default_factory=list)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance à vol d'oiseau (formule de haversine) entre deux points (lat, lon)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * RAYON_TERRE_KM * math.asin(math.sqrt(h))


def points_de_controle(
    trace: list[tuple[float, float]], pas_km: float = PAS_KM
) -> list[tuple[tuple[float, float], float]]:
    """Points le long du tracé, tous les `pas_km`, avec leur kilométrage depuis le départ.

    Comparer chaque station à ces points (et non à chaque segment) suffit : l'erreur
    reste inférieure à la moitié du pas, et le calcul reste rapide.
    """
    if not trace:
        return []
    points = [(trace[0], 0.0)]
    parcouru = 0.0
    prochain = pas_km
    for precedent, courant in zip(trace, trace[1:], strict=False):
        segment = distance_km(precedent, courant)
        while segment > 0 and parcouru + segment >= prochain:
            t = (prochain - parcouru) / segment
            point = (
                precedent[0] + t * (courant[0] - precedent[0]),
                precedent[1] + t * (courant[1] - precedent[1]),
            )
            points.append((point, prochain))
            prochain += pas_km
        parcouru += segment
    points.append((trace[-1], parcouru))
    return points


def cadre(trace: list[tuple[float, float]], marge_km: float) -> tuple[float, float, float, float]:
    """Rectangle (lat_min, lon_min, lat_max, lon_max) qui contient le tracé, élargi de la marge."""
    lats = [p[0] for p in trace]
    lons = [p[1] for p in trace]
    marge_lat = marge_km / 111.0
    marge_lon = marge_km / (111.0 * max(math.cos(math.radians(sum(lats) / len(lats))), 0.1))
    return (
        min(lats) - marge_lat,
        min(lons) - marge_lon,
        max(lats) + marge_lat,
        max(lons) + marge_lon,
    )


def stations_le_long(
    stations: list[Station],
    trace: list[tuple[float, float]],
    detour_km: float,
    carburant: str,
) -> list[StationSurTrajet]:
    """Garde les stations à moins de `detour_km` du tracé, les moins chères d'abord."""
    controle = points_de_controle(trace)
    if not controle:
        return []
    # Projection plane locale (équirectangulaire) : à l'échelle de quelques km, l'écart
    # avec la vraie distance est négligeable, et la comparaison évite la trigonométrie.
    km_par_deg_lon = 111.32 * math.cos(math.radians(sum(p[0][0] for p in controle) / len(controle)))
    km_par_deg_lat = 110.57
    plans = [(p[0] * km_par_deg_lat, p[1] * km_par_deg_lon, p, km) for p, km in controle]
    seuil2 = detour_km**2

    retenues: dict[str, StationSurTrajet] = {}
    for station in stations:
        y, x = station.lat * km_par_deg_lat, station.lon * km_par_deg_lon
        d2, point, km = min(((py - y) ** 2 + (px - x) ** 2, p, k) for py, px, p, k in plans)
        if d2 <= seuil2:
            ecart = distance_km((station.lat, station.lon), point)
            retenues[station.id] = StationSurTrajet(station, round(ecart, 2), round(km, 1))
    triees = trier_par_prix([s.station for s in retenues.values()], carburant)
    return [retenues[s.id] for s in triees]


class ClientTrajet:
    def __init__(self, client_prix: ClientPrix, client: httpx.Client | None = None):
        self._prix = client_prix
        self._client = client or httpx.Client(timeout=20.0)

    def geocoder(self, adresse: str) -> Etape:
        reponse = self._client.get(URL_GEOCODAGE, params={"q": adresse, "limit": 1})
        reponse.raise_for_status()
        resultats = reponse.json().get("features", [])
        if not resultats:
            raise AdresseIntrouvable(adresse)
        lon, lat = resultats[0]["geometry"]["coordinates"]
        libelle = resultats[0].get("properties", {}).get("label", adresse)
        return Etape(adresse=adresse, libelle=libelle, lat=float(lat), lon=float(lon))

    def itineraire(self, etapes: list[Etape]) -> tuple[list[tuple[float, float]], float, float]:
        """Renvoie (tracé en (lat, lon), distance en km, durée en minutes)."""

        def lon_lat(e: Etape) -> str:
            return f"{e.lon},{e.lat}"

        params = {
            "resource": "bdtopo-osrm",
            "profile": "car",
            "optimization": "fastest",
            "start": lon_lat(etapes[0]),
            "end": lon_lat(etapes[-1]),
            "geometryFormat": "geojson",
            "getSteps": "false",
            "getBbox": "false",
            "crs": "EPSG:4326",
            "distanceUnit": "kilometer",
            "timeUnit": "minute",
        }
        if len(etapes) > 2:
            params["intermediates"] = "|".join(lon_lat(e) for e in etapes[1:-1])
        reponse = self._client.get(URL_ITINERAIRE, params=params)
        reponse.raise_for_status()
        corps = reponse.json()
        trace = [(float(lat), float(lon)) for lon, lat in corps["geometry"]["coordinates"]]
        return trace, float(corps["distance"]), float(corps["duration"])

    def calculer(self, adresses: list[str], carburant: str, detour_km: float) -> Trajet:
        etapes = [self.geocoder(a) for a in adresses]
        trace, distance, duree = self.itineraire(etapes)
        candidates = self._prix.stations_dans_cadre(*cadre(trace, detour_km), carburant)
        return Trajet(
            etapes=etapes,
            distance_km=round(distance, 1),
            duree_min=round(duree),
            trace=trace,
            stations=stations_le_long(candidates, trace, detour_km, carburant),
        )
