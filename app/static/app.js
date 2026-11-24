"use strict";

const ZOOM_MIN = 10;        // en dessous, la zone est trop grande pour une requête
const RAYON_MAX_KM = 25;

const carte = L.map("carte").setView([46.6, 2.4], 6);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(carte);

const calque = L.layerGroup().addTo(carte);
const choix = document.getElementById("carburant");
const etat = document.getElementById("etat");
const liste = document.getElementById("liste");
let requeteEnCours = null;

function formaterPrix(prix) {
  return prix.toFixed(3).replace(".", ",") + " €/L";
}

function formaterDate(iso) {
  if (!iso) return "date inconnue";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

// Vert pour la moins chère, rouge pour la plus chère de la zone affichée.
function couleur(prix, min, max) {
  const t = max > min ? (prix - min) / (max - min) : 0;
  return `hsl(${Math.round(120 * (1 - t))}, 70%, 42%)`;
}

// Construit le contenu d'une bulle sans innerHTML : les données viennent d'une source externe.
function bulle(station, carburants) {
  const div = document.createElement("div");
  const titre = document.createElement("strong");
  titre.textContent = `${station.adresse}, ${station.cp} ${station.ville}`;
  div.appendChild(titre);
  const ul = document.createElement("ul");
  for (const [code, info] of Object.entries(station.prix)) {
    const li = document.createElement("li");
    li.textContent = `${carburants[code] || code} : ${formaterPrix(info.prix)} (${formaterDate(info.maj)})`;
    ul.appendChild(li);
  }
  div.appendChild(ul);
  return div;
}

async function charger() {
  if (carte.getZoom() < ZOOM_MIN) {
    calque.clearLayers();
    liste.replaceChildren();
    etat.textContent = "Zoome sur une zone pour voir les stations.";
    return;
  }
  const centre = carte.getCenter();
  const coin = carte.getBounds().getNorthEast();
  const rayonKm = Math.min(centre.distanceTo(coin) / 1000, RAYON_MAX_KM);
  const carburant = choix.value;
  const parametres = new URLSearchParams({
    lat: centre.lat.toFixed(5),
    lon: centre.lng.toFixed(5),
    rayon_km: rayonKm.toFixed(1),
    carburant,
  });

  requeteEnCours?.abort();
  requeteEnCours = new AbortController();
  etat.textContent = "Chargement…";
  try {
    const reponse = await fetch(`/api/stations?${parametres}`, { signal: requeteEnCours.signal });
    if (!reponse.ok) throw new Error(`HTTP ${reponse.status}`);
    afficher(await reponse.json(), carburant);
  } catch (erreur) {
    if (erreur.name !== "AbortError") etat.textContent = `Erreur : ${erreur.message}`;
  }
}

function afficher(stations, carburant) {
  calque.clearLayers();
  liste.replaceChildren();
  const nom = window.carburants[carburant];
  etat.textContent = `${stations.length} station(s) avec du ${nom} dans la zone.`;
  if (stations.length === 0) return;

  const prix = stations.map((s) => s.prix[carburant].prix);
  const min = Math.min(...prix);
  const max = Math.max(...prix);

  for (const station of stations) {
    const p = station.prix[carburant];
    const marqueur = L.circleMarker([station.lat, station.lon], {
      radius: 9,
      color: "#222",
      weight: 1,
      fillColor: couleur(p.prix, min, max),
      fillOpacity: 0.9,
    })
      .bindTooltip(formaterPrix(p.prix))
      .bindPopup(() => bulle(station, window.carburants))
      .addTo(calque);

    if (liste.children.length < 20) {
      const li = document.createElement("li");
      const montant = document.createElement("span");
      montant.className = "prix";
      montant.textContent = formaterPrix(p.prix);
      const lieu = document.createElement("div");
      lieu.textContent = `${station.adresse}, ${station.ville}`;
      const maj = document.createElement("div");
      maj.className = "maj";
      maj.textContent = `mis à jour le ${formaterDate(p.maj)}`;
      li.append(montant, lieu, maj);
      li.addEventListener("click", () => {
        carte.setView([station.lat, station.lon], Math.max(carte.getZoom(), 14));
        marqueur.openPopup();
      });
      liste.appendChild(li);
    }
  }
}

document.getElementById("localiser").addEventListener("click", () => {
  if (!navigator.geolocation) {
    etat.textContent = "Géolocalisation indisponible dans ce navigateur.";
    return;
  }
  // Le navigateur ne la permet qu'en HTTPS (ou sur localhost).
  navigator.geolocation.getCurrentPosition(
    (pos) => carte.setView([pos.coords.latitude, pos.coords.longitude], 12),
    () => (etat.textContent = "Position refusée ou indisponible (HTTPS requis)."),
  );
});

async function demarrer() {
  window.carburants = await (await fetch("/api/carburants")).json();
  for (const [code, nom] of Object.entries(window.carburants)) {
    choix.add(new Option(nom, code, false, code === "e85"));
  }
  choix.addEventListener("change", charger);
  carte.on("moveend", charger);
  charger();
}

demarrer();
