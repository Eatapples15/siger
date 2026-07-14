"""Geocodifica di fallback per gli eventi senza coordinate estratte dal diario.

Solo una minoranza delle note diario riporta 'coordinate lat, lon' in chiaro (vedi
siger_parser.estrai_dettagli_diario): per mostrare in mappa TUTTI gli eventi gestiti,
i restanti vengono posizionati in modo approssimato sul comune tramite Nominatim
(OpenStreetMap), con una cache locale su file per evitare richieste ripetute e
rispettare il limite di 1 richiesta/secondo di Nominatim.
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

_CACHE_PATH = Path(__file__).parent / "comuni_coords_cache.json"
_USER_AGENT = "siger-report-basilicata/1.0 (uso interno protezione civile regionale)"


def _carica_cache() -> dict:
    if _CACHE_PATH.exists():
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _salva_cache(cache: dict):
    _CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def _geocodifica_nominatim(comune: str, provincia: str):
    query = f"{comune}, {provincia}, Basilicata, Italia"
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
        risultati = resp.json()
    except requests.RequestException:
        return None
    if not risultati:
        return None
    return [float(risultati[0]["lat"]), float(risultati[0]["lon"])]


def geocodifica_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Riempie lat/lon mancanti con una stima a livello di comune (Nominatim), aggiungendo
    la colonna 'posizione_precisa' (True se le coordinate vengono dal diario, False se
    approssimate sul comune) così la mappa può distinguerle."""
    if df.empty:
        return df

    df = df.copy()
    df["posizione_precisa"] = df["lat"].notna() & df["lon"].notna()

    da_geocodificare = df.loc[~df["posizione_precisa"], ["comune", "provincia"]].dropna().drop_duplicates()
    cache = _carica_cache()
    cache_aggiornata = False
    for _, riga in da_geocodificare.iterrows():
        chiave = f"{riga['comune']}|{riga['provincia']}"
        if chiave in cache:
            continue
        coords = _geocodifica_nominatim(riga["comune"], riga["provincia"])
        if coords is not None:
            # I fallimenti (Nominatim irraggiungibile/bloccato/comune non trovato) non vengono
            # salvati: altrimenti un blocco temporaneo (es. troppe richieste ravvicinate)
            # marcherebbe quei comuni come "introvabili" per sempre invece di riprovare dopo.
            cache[chiave] = coords
            cache_aggiornata = True
        time.sleep(1)  # limite Nominatim: 1 richiesta/secondo

    if cache_aggiornata:
        _salva_cache(cache)

    def _lookup(row):
        if row["posizione_precisa"]:
            return row["lat"], row["lon"]
        coords = cache.get(f"{row['comune']}|{row['provincia']}")
        return tuple(coords) if coords else (None, None)

    coordinate = df.apply(_lookup, axis=1, result_type="expand")
    coordinate.columns = ["lat", "lon"]
    df["lat"] = coordinate["lat"]
    df["lon"] = coordinate["lon"]
    return df
