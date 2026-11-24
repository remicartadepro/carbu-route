"use strict";

const ZOOM_MIN = 10;        // en dessous, la zone est trop grande pour une requête
const RAYON_MAX_KM = 25;
const TAILLE_LISTE = 20;
const MAX_ADRESSES = 6;     // départ + 4 étapes + arrivée (limite de l'API)
const GRIS_PERIME = "#9a9aa2"; // prix de plus de 15 jours (calculé par le serveur)

const carte = L.map("carte").setView([46.6, 2.4], 6);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(carte);

const calqueStations = L.layerGroup().addTo(carte);
const calqueTrajet = L.layerGroup().addTo(carte);
const choix = document.getElementById("carburant");
const etat = document.getElementById("etat");
const liste = document.getElementById("liste");
const titreListe = document.getElementById("titre-liste");
const formulaire = document.getElementById("form-trajet");
const champsAdresses = document.getElementById("adresses");
const detour = document.getElementById("detour");
let requeteEnCours = null;
let trajetActif = false;   // en mode trajet, déplacer la carte ne recharge pas les stations

function formaterPrix(prix) {
  return prix.toFixed(3).replace(".", ",") + " €/L";
}

function formaterDate(iso) {
  if (!iso) return "date inconnue";
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

function formaterKm(km) {
  return km.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " km";
}

// Vert pour la moins chère, rouge pour la plus chère de la sélection.
function couleur(prix, min, max) {
  const t = max > min ? (prix - min) / (max - min) : 0;
  return `hsl(${Math.round(120 * (1 - t))}, 70%, 42%)`;
}

// Construit le contenu d'une bulle sans innerHTML : les données viennent d'une source externe.
function bulle(station, carburants, complement) {
  const div = document.createElement("div");
  const titre = document.createElement("strong");
  titre.textContent = `${station.adresse}, ${station.cp} ${station.ville}`;
  div.appendChild(titre);
  if (complement) {
    const ligne = document.createElement("div");
    ligne.textContent = complement;
    div.appendChild(ligne);
  }
  const ul = document.createElement("ul");
  for (const [code, info] of Object.entries(station.prix)) {
    const li = document.createElement("li");
    li.textContent = `${carburants[code] || code} : ${formaterPrix(info.prix)} (${formaterDate(info.maj)})`;
    if (info.perime) li.className = "perime";
    ul.appendChild(li);
  }
  div.appendChild(ul);
  return div;
}

async function appeler(url, options = {}) {
  requeteEnCours?.abort();
  requeteEnCours = new AbortController();
  const reponse = await fetch(url, { ...options, signal: requeteEnCours.signal });
  if (!reponse.ok) {
    let detail = `HTTP ${reponse.status}`;
    try {
      const corps = await reponse.json();
      if (typeof corps.detail === "string") detail = corps.detail;
    } catch { /* corps non JSON : on garde le code HTTP */ }
    throw new Error(detail);
  }
  return reponse.json();
}

// ---------- Mode « autour de moi » : les stations de la zone affichée ----------

async function chargerZone() {
  if (trajetActif) return;
  if (carte.getZoom() < ZOOM_MIN) {
    calqueStations.clearLayers();
    liste.replaceChildren();
    etat.textContent = "Zoome sur une zone ou calcule un trajet.";
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
  etat.textContent = "Chargement…";
  try {
    const stations = await appeler(`/api/stations?${parametres}`);
    titreListe.textContent = "Les moins chères ici";
    afficher(stations.map((station) => ({ station })), carburant);
    etat.textContent = `${stations.length} station(s) avec du ${window.carburants[carburant]} dans la zone.`;
  } catch (erreur) {
    if (erreur.name !== "AbortError") etat.textContent = `Erreur : ${erreur.message}`;
  }
}

// ---------- Mode trajet ----------

function ajouterChamp(valeur = "") {
  const champ = document.createElement("input");
  champ.type = "text";
  champ.required = true;
  champ.minLength = 2;
  champ.value = valeur;
  champ.autocomplete = "street-address";
  champsAdresses.appendChild(champ);
  renommerChamps();
  return champ;
}

function renommerChamps() {
  const champs = [...champsAdresses.querySelectorAll("input")];
  champs.forEach((champ, i) => {
    const nom = i === 0 ? "Départ" : i === champs.length - 1 ? "Arrivée" : `Étape ${i}`;
    champ.placeholder = nom;
    champ.setAttribute("aria-label", nom);
  });
  document.getElementById("ajout-etape").disabled = champs.length >= MAX_ADRESSES;
}

async function calculerTrajet() {
  const adresses = [...champsAdresses.querySelectorAll("input")]
    .map((champ) => champ.value.trim())
    .filter(Boolean);
  if (adresses.length < 2) {
    etat.textContent = "Il faut au moins un départ et une arrivée.";
    return;
  }
  const carburant = choix.value;
  etat.textContent = "Calcul du trajet…";
  try {
    const trajet = await appeler("/api/trajet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adresses, carburant, detour_km: Number(detour.value) }),
    });
    trajetActif = true;
    dessinerTrajet(trajet);
    titreListe.textContent = "Les moins chères sur le trajet";
    afficher(trajet.stations, carburant);
    const heures = Math.floor(trajet.duree_min / 60);
    const minutes = trajet.duree_min % 60;
    const duree = heures ? `${heures} h ${String(minutes).padStart(2, "0")}` : `${minutes} min`;
    etat.textContent =
      `${formaterKm(trajet.distance_km)}, ${duree} · ` +
      `${trajet.stations.length} station(s) avec du ${window.carburants[carburant]} ` +
      `à moins de ${detour.value} km de la route.`;
  } catch (erreur) {
    if (erreur.name !== "AbortError") etat.textContent = `Erreur : ${erreur.message}`;
  }
}

function dessinerTrajet(trajet) {
  calqueTrajet.clearLayers();
  const ligne = L.polyline(trajet.trace, { color: "#2f6fde", weight: 5, opacity: 0.75 }).addTo(calqueTrajet);
  trajet.etapes.forEach((etape, i) => {
    L.circleMarker([etape.lat, etape.lon], {
      radius: 7, color: "#2f6fde", weight: 3, fillColor: "#fff", fillOpacity: 1,
    })
      .bindTooltip(`${i + 1}. ${etape.libelle}`)
      .addTo(calqueTrajet);
  });
  carte.fitBounds(ligne.getBounds(), { padding: [30, 30] });
}

function effacerTrajet() {
  trajetActif = false;
  calqueTrajet.clearLayers();
  chargerZone();
}

// ---------- Affichage commun : ronds sur la carte et liste ----------

// `elements` : [{ station, ecart_km?, km_depuis_depart? }], déjà triés par le serveur.
function afficher(elements, carburant) {
  calqueStations.clearLayers();
  liste.replaceChildren();
  if (elements.length === 0) return;

  // L'échelle de couleurs ne tient compte que des prix frais (moins de 15 jours).
  const frais = elements
    .map((e) => e.station.prix[carburant])
    .filter((p) => !p.perime)
    .map((p) => p.prix);
  const min = Math.min(...frais);
  const max = Math.max(...frais);

  for (const { station, ecart_km: ecart, km_depuis_depart: km } of elements) {
    const p = station.prix[carburant];
    const position =
      km === undefined ? "" : `au km ${Math.round(km)} du trajet · à ${formaterKm(ecart)} de la route`;
    const marqueur = L.circleMarker([station.lat, station.lon], {
      radius: 9,
      color: "#222",
      weight: 1,
      fillColor: p.perime ? GRIS_PERIME : couleur(p.prix, min, max),
      fillOpacity: p.perime ? 0.6 : 0.9,
    })
      .bindTooltip(formaterPrix(p.prix) + (p.perime ? " (ancien)" : ""))
      .bindPopup(() => bulle(station, window.carburants, position))
      .addTo(calqueStations);

    if (liste.children.length < TAILLE_LISTE) {
      const li = document.createElement("li");
      if (p.perime) li.className = "perime";
      const montant = document.createElement("span");
      montant.className = "prix";
      montant.textContent = formaterPrix(p.prix);
      const lieu = document.createElement("div");
      lieu.textContent = `${station.adresse}, ${station.ville}`;
      const details = document.createElement("div");
      details.className = "maj";
      details.textContent =
        (position ? position + " · " : "") +
        `mis à jour le ${formaterDate(p.maj)}` +
        (p.perime ? " · ancien, à vérifier" : "");
      li.append(montant, lieu, details);
      li.addEventListener("click", () => {
        carte.setView([station.lat, station.lon], Math.max(carte.getZoom(), 14));
        marqueur.openPopup();
      });
      liste.appendChild(li);
    }
  }
}

// ---------- Démarrage ----------

document.getElementById("localiser").addEventListener("click", () => {
  if (!navigator.geolocation) {
    etat.textContent = "Géolocalisation indisponible dans ce navigateur.";
    return;
  }
  // Le navigateur ne la permet qu'en HTTPS (ou sur localhost).
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      if (trajetActif) effacerTrajet();
      carte.setView([pos.coords.latitude, pos.coords.longitude], 12);
    },
    () => (etat.textContent = "Position refusée ou indisponible (HTTPS requis)."),
  );
});

document.getElementById("ajout-etape").addEventListener("click", () => {
  const champs = champsAdresses.querySelectorAll("input");
  // Une étape s'insère juste avant l'arrivée.
  const nouveau = ajouterChamp();
  champsAdresses.insertBefore(nouveau, champs[champs.length - 1]);
  renommerChamps();
  nouveau.focus();
});

document.getElementById("effacer").addEventListener("click", () => {
  champsAdresses.replaceChildren();
  ajouterChamp();
  ajouterChamp();
  effacerTrajet();
});

formulaire.addEventListener("submit", (evenement) => {
  evenement.preventDefault();
  calculerTrajet();
});

async function demarrer() {
  window.carburants = await (await fetch("/api/carburants")).json();
  for (const [code, nom] of Object.entries(window.carburants)) {
    choix.add(new Option(nom, code, false, code === "e85"));
  }
  ajouterChamp();
  ajouterChamp();
  choix.addEventListener("change", () => (trajetActif ? calculerTrajet() : chargerZone()));
  carte.on("moveend", chargerZone);
  chargerZone();
}

demarrer();
