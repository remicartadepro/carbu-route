"""Tests hors ligne : l'API officielle est remplacée par un faux transport httpx."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, client_prix
from app.prix import (
    TAILLE_PAGE,
    ClientPrix,
    construire_filtre,
    normaliser,
    trier_par_prix,
)

# Forme d'une ligne du flux v2 (valeurs inventées).
LIGNE_A = {
    "id": 1,
    "adresse": "1 route de Test",
    "ville": "Exempleville",
    "cp": "00001",
    "geom": {"lat": 43.5, "lon": 2.3},
    "e85_prix": 0.799,
    "e85_maj": "2026-11-24T08:00:00+00:00",
    "gazole_prix": 1.659,
    "gazole_maj": "2026-11-24T08:00:00+00:00",
}
LIGNE_B = {
    "id": 2,
    "adresse": "2 avenue Bidon",
    "ville": "Exempleville",
    "cp": "00001",
    "latitude": "4351000",
    "longitude": "231000",
    "e85_prix": 0.749,
    "e85_maj": "2026-11-24T07:00:00+00:00",
}


def test_normaliser_lit_geom_et_les_prix():
    station = normaliser(LIGNE_A)
    assert station is not None
    assert (station.lat, station.lon) == (43.5, 2.3)
    assert station.prix_de("e85") == 0.799
    assert station.prix_de("gazole") == 1.659
    assert station.prix_de("sp98") is None


def test_normaliser_ancien_format_des_coordonnees():
    station = normaliser(LIGNE_B)
    assert station is not None
    assert station.lat == pytest.approx(43.51)
    assert station.lon == pytest.approx(2.31)


def test_normaliser_ignore_une_station_sans_position():
    assert normaliser({"id": 3, "e85_prix": 0.8}) is None


def test_filtre_borne_le_rayon_et_refuse_un_carburant_inconnu():
    filtre = construire_filtre(43.5, 2.3, 500, "e85")
    assert "geom'POINT(2.3 43.5)'" in filtre
    assert "50km" in filtre
    assert "e85_prix is not null" in filtre
    with pytest.raises(ValueError):
        construire_filtre(43.5, 2.3, 10, "kerosene")


def test_tri_moins_cher_d_abord():
    stations = [normaliser(LIGNE_A), normaliser(LIGNE_B)]
    assert [s.id for s in trier_par_prix(stations, "e85")] == ["2", "1"]


def faux_client(pages):
    """Client httpx qui renvoie les pages données, une par appel, et compte les appels."""
    appels = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        appels.append(requete)
        return httpx.Response(200, json={"results": pages[len(appels) - 1]})

    return ClientPrix(httpx.Client(transport=httpx.MockTransport(repondre))), appels


def test_pagination_et_cache():
    pleine = [dict(LIGNE_A, id=i) for i in range(TAILLE_PAGE)]
    client, appels = faux_client([pleine, [LIGNE_B]])

    resultat = client.stations_autour(43.5, 2.3, 10, "e85")
    assert len(resultat) == TAILLE_PAGE + 1
    assert len(appels) == 2
    assert appels[1].url.params["offset"] == str(TAILLE_PAGE)

    client.stations_autour(43.5, 2.3, 10, "e85")
    assert len(appels) == 2, "la 2e demande doit sortir du cache"


@pytest.fixture
def api():
    client, _ = faux_client([[LIGNE_A, LIGNE_B]])
    app.dependency_overrides[client_prix] = lambda: client
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_stations(api):
    reponse = api.get("/api/stations", params={"lat": 43.5, "lon": 2.3, "carburant": "e85"})
    assert reponse.status_code == 200
    corps = reponse.json()
    assert [s["id"] for s in corps] == ["2", "1"]
    assert corps[0]["prix"]["e85"]["prix"] == 0.749


def test_api_refuse_un_carburant_inconnu(api):
    reponse = api.get("/api/stations", params={"lat": 43.5, "lon": 2.3, "carburant": "kerosene"})
    assert reponse.status_code == 422


def test_sante_et_page(api):
    assert api.get("/healthz").json() == {"statut": "ok"}
    assert "carbu-route" in api.get("/").text
