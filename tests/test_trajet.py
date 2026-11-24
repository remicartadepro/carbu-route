"""Tests hors ligne du trajet : géocodage, itinéraire et prix sont simulés."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, client_trajet
from app.prix import ClientPrix
from app.trajet import (
    ClientTrajet,
    cadre,
    distance_km,
    points_de_controle,
    stations_le_long,
)

# Tracé fictif : une ligne droite plein est, le long du parallèle 43,5° N (≈ 24 km).
TRACE = [(43.5, 2.0), (43.5, 2.15), (43.5, 2.3)]


def station(id_, lat, lon, prix, maj="2099-01-01T00:00:00+00:00"):
    return {
        "id": id_,
        "adresse": f"station {id_}",
        "ville": "X",
        "cp": "00000",
        "geom": {"lat": lat, "lon": lon},
        "e85_prix": prix,
        "e85_maj": maj,
    }


def test_distance_haversine():
    # 1° de latitude ≈ 111,2 km
    assert distance_km((43.0, 2.0), (44.0, 2.0)) == pytest.approx(111.2, abs=0.2)


def test_points_de_controle_reguliers():
    points = points_de_controle(TRACE, pas_km=1)
    longueur = distance_km(TRACE[0], TRACE[-1])
    assert points[0] == (TRACE[0], 0.0)
    assert points[-1][1] == pytest.approx(longueur, abs=0.01)
    assert len(points) == int(longueur) + 2  # un point par km, plus départ et arrivée


def test_cadre_englobe_le_trace_avec_sa_marge():
    lat_min, lon_min, lat_max, lon_max = cadre(TRACE, marge_km=2)
    assert lat_min < 43.5 < lat_max
    assert lon_min < 2.0 and lon_max > 2.3
    assert (lat_max - 43.5) == pytest.approx(2 / 111, rel=0.01)


def test_garde_les_stations_proches_du_trace_les_moins_cheres_d_abord():
    from app.prix import normaliser

    candidates = [
        normaliser(station(1, 43.505, 2.10, 0.90)),  # ≈ 0,6 km du tracé
        normaliser(station(2, 43.49, 2.25, 0.80)),  # ≈ 1,1 km
        normaliser(station(3, 43.60, 2.15, 0.70)),  # ≈ 11 km : trop loin
    ]
    retenues = stations_le_long(candidates, TRACE, detour_km=2, carburant="e85")
    assert [s.station.id for s in retenues] == ["2", "1"]
    assert retenues[0].ecart_km == pytest.approx(1.1, abs=0.3)
    assert retenues[0].km_depuis_depart == pytest.approx(20.2, abs=0.6)


def faux_services(requetes):
    """Simule l'IGN (géocodage, itinéraire) et l'export des prix, selon le chemin appelé."""

    def repondre(requete: httpx.Request) -> httpx.Response:
        requetes.append(requete)
        chemin = requete.url.path
        if chemin.endswith("/geocodage/search"):
            q = requete.url.params["q"]
            if q == "nulle part":
                return httpx.Response(200, json={"features": []})
            lon = {"Ville A": 2.0, "Ville B": 2.15, "Ville C": 2.3}[q]
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "geometry": {"coordinates": [lon, 43.5]},
                            "properties": {"label": f"{q} (France)"},
                        }
                    ]
                },
            )
        if chemin.endswith("/navigation/itineraire"):
            return httpx.Response(
                200,
                json={
                    "distance": 24.2,
                    "duration": 21.6,
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon, lat] for lat, lon in TRACE],
                    },
                },
            )
        if chemin.endswith("/exports/json"):
            return httpx.Response(
                200,
                json=[
                    station(1, 43.505, 2.10, 0.90),
                    station(3, 43.60, 2.15, 0.70),
                ],
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(repondre))


@pytest.fixture
def api_et_requetes():
    requetes = []
    http = faux_services(requetes)
    client = ClientTrajet(ClientPrix(http), http)
    app.dependency_overrides[client_trajet] = lambda: client
    yield TestClient(app), requetes
    app.dependency_overrides.clear()


def test_api_trajet_avec_une_etape(api_et_requetes):
    api, requetes = api_et_requetes
    reponse = api.post(
        "/api/trajet", json={"adresses": ["Ville A", "Ville B", "Ville C"], "detour_km": 2}
    )
    assert reponse.status_code == 200
    corps = reponse.json()
    assert [e["libelle"] for e in corps["etapes"]] == [
        "Ville A (France)",
        "Ville B (France)",
        "Ville C (France)",
    ]
    assert corps["distance_km"] == 24.2
    assert [s["station"]["id"] for s in corps["stations"]] == ["1"]

    itineraire = next(r for r in requetes if r.url.path.endswith("/itineraire"))
    assert itineraire.url.params["start"] == "2.0,43.5"
    assert itineraire.url.params["intermediates"] == "2.15,43.5"
    assert itineraire.url.params["end"] == "2.3,43.5"
    export = next(r for r in requetes if r.url.path.endswith("/exports/json"))
    assert export.url.params["where"].startswith("in_bbox(geom, ")


def test_api_trajet_adresse_introuvable(api_et_requetes):
    api, _ = api_et_requetes
    reponse = api.post("/api/trajet", json={"adresses": ["Ville A", "nulle part"]})
    assert reponse.status_code == 404
    assert "nulle part" in reponse.json()["detail"]


def test_api_trajet_refuse_une_seule_adresse(api_et_requetes):
    api, _ = api_et_requetes
    assert api.post("/api/trajet", json={"adresses": ["Ville A"]}).status_code == 422
