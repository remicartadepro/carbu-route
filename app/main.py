"""Serveur web : la carte (page statique) et l'API JSON qui l'alimente."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.prix import CARBURANTS, RAYON_MAX_KM, ClientPrix

DOSSIER_STATIQUE = Path(__file__).parent / "static"

app = FastAPI(
    title="carbu-route",
    description="Prix des carburants autour d'un point, d'après les données ouvertes de l'État.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=DOSSIER_STATIQUE), name="static")

_client_prix = ClientPrix()


def client_prix() -> ClientPrix:
    return _client_prix


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
