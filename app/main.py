"""Serveur web : la carte (page statique) et l'API JSON qui l'alimente."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.prix import CARBURANTS, RAYON_MAX_KM, ClientPrix
from app.trajet import DETOUR_MAX_KM, AdresseIntrouvable, ClientTrajet

DOSSIER_STATIQUE = Path(__file__).parent / "static"

app = FastAPI(
    title="carbu-route",
    description=(
        "Prix des carburants autour d'un point ou le long d'un trajet, "
        "d'après les données ouvertes de l'État."
    ),
    version="0.2.0",
)
app.mount("/static", StaticFiles(directory=DOSSIER_STATIQUE), name="static")

_client_prix = ClientPrix()
_client_trajet = ClientTrajet(_client_prix)


def client_prix() -> ClientPrix:
    return _client_prix


def client_trajet() -> ClientTrajet:
    return _client_trajet


@app.get("/", include_in_schema=False)
def accueil() -> FileResponse:
    return FileResponse(DOSSIER_STATIQUE / "index.html")


@app.get("/healthz")
def sante() -> dict[str, str]:
    """Sonde de vie, pour le HEALTHCHECK de Docker et la supervision."""
    return {"statut": "ok"}


@app.get("/api/carburants")
def carburants() -> dict[str, str]:
    return CARBURANTS


@app.get("/api/stations")
def stations(
    client: Annotated[ClientPrix, Depends(client_prix)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    rayon_km: Annotated[float, Query(gt=0, le=RAYON_MAX_KM)] = 10,
    carburant: str = "e85",
) -> list[dict]:
    """Stations qui vendent `carburant` dans le rayon, les moins chères d'abord."""
    if carburant not in CARBURANTS:
        raise HTTPException(status_code=422, detail=f"carburant inconnu : {carburant}")
    try:
        resultat = client.stations_autour(lat, lon, rayon_km, carburant)
    except httpx.HTTPError as erreur:
        raise HTTPException(status_code=502, detail="source des prix injoignable") from erreur
    return [asdict(s) for s in resultat]


class DemandeTrajet(BaseModel):
    adresses: list[Annotated[str, Field(min_length=2, max_length=200)]] = Field(
        min_length=2, max_length=6, description="Départ, étapes éventuelles, arrivée"
    )
    carburant: str = "e85"
    detour_km: float = Field(default=2, gt=0, le=DETOUR_MAX_KM)


@app.post("/api/trajet")
def trajet(
    demande: DemandeTrajet,
    client: Annotated[ClientTrajet, Depends(client_trajet)],
) -> dict:
    """Itinéraire entre les adresses et stations à moins de `detour_km` du tracé."""
    if demande.carburant not in CARBURANTS:
        raise HTTPException(status_code=422, detail=f"carburant inconnu : {demande.carburant}")
    try:
        resultat = client.calculer(demande.adresses, demande.carburant, demande.detour_km)
    except AdresseIntrouvable as erreur:
        raise HTTPException(status_code=404, detail=f"adresse introuvable : {erreur}") from erreur
    except httpx.HTTPError as erreur:
        raise HTTPException(
            status_code=502, detail="service d'itinéraire ou de prix injoignable"
        ) from erreur
    return asdict(resultat)
