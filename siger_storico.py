"""Archivio storico persistente degli eventi, per il confronto anno-su-anno.

Seed iniziale: foglio 'STORICO' del workbook Excel che la sala operativa mantiene a mano
(REPORTAIB - SALA CONTROLLO.xlsx), normalizzato allo stesso schema del dataset live prodotto
da siger_parser.costruisci_dataset_consolidato. Da lì in avanti l'archivio si arricchisce da
solo: ogni volta che la pipeline live estrae dati dal portale, upsert_archivio() li aggiunge
(deduplicando per id_evento, con priorità ai dati più recenti).
"""
from pathlib import Path

import openpyxl
import pandas as pd

_ARCHIVIO_PATH = Path(__file__).parent / "dati_storici.csv"
_COLONNE_ARCHIVIO = ["id_evento", "comune", "provincia", "contesto", "tipologia", "data_inizio", "data_fine"]


def _combina_data_ora(data, ora):
    if data is None:
        return None
    if ora is None:
        return data
    return data.replace(hour=ora.hour, minute=ora.minute, second=getattr(ora, "second", 0))


def importa_storico_excel(source) -> pd.DataFrame:
    """Legge il foglio 'STORICO' del workbook Excel e lo normalizza allo schema comune
    (id_evento, comune, provincia, contesto, tipologia, data_inizio, data_fine).

    source: path o file-like (es. da st.file_uploader)."""
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    ws = wb["STORICO"]

    records = []
    for row in ws.iter_rows(min_row=3, max_col=14, values_only=True):
        id_evento = row[1]
        if id_evento is None:
            continue
        records.append({
            "id_evento": int(id_evento),
            "comune": row[7],
            "provincia": row[8],
            "contesto": row[11],
            "tipologia": row[12],
            "data_inizio": _combina_data_ora(row[3], row[4]),
            "data_fine": _combina_data_ora(row[5], row[6]),
        })
    df = pd.DataFrame.from_records(records, columns=_COLONNE_ARCHIVIO)
    df["data_inizio"] = pd.to_datetime(df["data_inizio"])
    df["data_fine"] = pd.to_datetime(df["data_fine"])
    return df


def carica_archivio() -> pd.DataFrame:
    if _ARCHIVIO_PATH.exists():
        return pd.read_csv(_ARCHIVIO_PATH, parse_dates=["data_inizio", "data_fine"])
    return pd.DataFrame(columns=_COLONNE_ARCHIVIO)


def upsert_archivio(nuovi_eventi: pd.DataFrame) -> pd.DataFrame:
    """Unisce nuovi_eventi con l'archivio su disco, deduplicando per id_evento (tiene la
    versione più recente — i dati passati per ultimi in ordine di concatenazione vincono,
    quindi qui i dati live sovrascrivono quelli storici per gli id in comune). Salva e
    restituisce l'archivio aggiornato."""
    if nuovi_eventi.empty:
        return carica_archivio()

    esistente = carica_archivio()
    colonne_presenti = [c for c in _COLONNE_ARCHIVIO if c in nuovi_eventi.columns]
    nuovi = nuovi_eventi[colonne_presenti].copy()

    combinato = nuovi if esistente.empty else pd.concat([esistente, nuovi], ignore_index=True)
    combinato = combinato.drop_duplicates(subset="id_evento", keep="last")
    combinato = combinato.sort_values("id_evento").reset_index(drop=True)
    combinato.to_csv(_ARCHIVIO_PATH, index=False)
    return combinato
