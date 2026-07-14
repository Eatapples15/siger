"""Calcolo del confronto anno-su-anno "stato campagna" (finestra 1/07 -> oggi a pari
data), condiviso tra la Dashboard (pages/1_Dashboard_Statistiche.py) e la pagina di
presentazione pubblica (pages/3_Presentazione_Campagna.py) — stessa logica, resa visiva
diversa in ciascuna pagina. Nessuna dipendenza da Streamlit: solo calcolo su DataFrame.
"""
from datetime import date

import pandas as pd

ORDINE_TIPOLOGIA = [
    "Incendio Boschivo", "Incendio non boschivo", "Incendio Interfaccia",
    "Altro Incendio", "Falso allarme", "Inserimento multiplo",
]
ORDINE_GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
ORDINE_FASCIA = ["Notte (00-06)", "Mattina (06-12)", "Pomeriggio (12-18)", "Sera (18-24)"]


def _fascia_oraria(ora: int) -> str:
    if ora < 6:
        return ORDINE_FASCIA[0]
    if ora < 12:
        return ORDINE_FASCIA[1]
    if ora < 18:
        return ORDINE_FASCIA[2]
    return ORDINE_FASCIA[3]


def _finestra_campagna(anno: int, oggi: date) -> tuple[date, date]:
    return date(anno, 7, 1), date(anno, oggi.month, oggi.day)


def confronto_categoria(df_prec, df_corr, colonna, anno_prec, anno_corr, ordine_fisso=None, top_n=None):
    """Tabella lunga (categoria, anno, eventi) per un confronto anno-su-anno a barre
    raggruppate: ordine delle categorie fisso se fornito, altrimenti per frequenza
    combinata decrescente (troncata a top_n se richiesto)."""
    c_prec = df_prec[colonna].fillna("Non specificato").value_counts()
    c_corr = df_corr[colonna].fillna("Non specificato").value_counts()
    tutte = set(c_prec.index) | set(c_corr.index)
    if ordine_fisso:
        ordine = [v for v in ordine_fisso if v in tutte] + sorted(v for v in tutte if v not in ordine_fisso)
    else:
        combinato = c_prec.reindex(tutte, fill_value=0).add(c_corr.reindex(tutte, fill_value=0))
        ordine = list(combinato.sort_values(ascending=False).index)
        if top_n:
            ordine = ordine[:top_n]
    righe = []
    for v in ordine:
        righe.append({"categoria": v, "anno": str(anno_corr), "eventi": int(c_corr.get(v, 0))})
        righe.append({"categoria": v, "anno": str(anno_prec), "eventi": int(c_prec.get(v, 0))})
    return pd.DataFrame(righe), ordine


def _cumulato_per_giorno_campagna(df: pd.DataFrame, inizio: date) -> pd.Series:
    g = df.copy()
    g["giorno_campagna"] = (g["data_inizio"].dt.date - inizio).map(lambda d: d.days)
    return g.groupby("giorno_campagna").size().sort_index().cumsum()


def calcola_confronto(archivio: pd.DataFrame, oggi: date | None = None) -> dict | None:
    """Calcola tutti i dati per il confronto anno-su-anno a pari data di campagna (1/07 ->
    oggi). Restituisce None se l'archivio è vuoto o non ci sono dati per l'anno precedente
    nella stessa finestra (nulla da confrontare)."""
    oggi = oggi or date.today()
    archivio = archivio.dropna(subset=["data_inizio"])
    if archivio.empty:
        return None

    anno_corrente, anno_precedente = oggi.year, oggi.year - 1
    inizio_corr, fine_corr = _finestra_campagna(anno_corrente, oggi)
    inizio_prec, fine_prec = _finestra_campagna(anno_precedente, oggi)
    arch_corr = archivio[archivio["data_inizio"].dt.date.between(inizio_corr, fine_corr)]
    arch_prec = archivio[archivio["data_inizio"].dt.date.between(inizio_prec, fine_prec)]
    if arch_prec.empty:
        return None

    tot_corr, tot_prec = len(arch_corr), len(arch_prec)
    variazione = round(100 * (tot_corr - tot_prec) / tot_prec, 1) if tot_prec else None

    cum_corr = _cumulato_per_giorno_campagna(arch_corr, inizio_corr)
    cum_prec = _cumulato_per_giorno_campagna(arch_prec, inizio_prec)
    giorno_max = max(
        int(cum_corr.index.max()) if len(cum_corr) else 0,
        int(cum_prec.index.max()) if len(cum_prec) else 0,
    )
    indice = pd.RangeIndex(0, giorno_max + 1)
    serie_corr = cum_corr.reindex(indice, method="ffill").fillna(0).astype(int)
    serie_prec = cum_prec.reindex(indice, method="ffill").fillna(0).astype(int)
    df_cum = pd.DataFrame({
        "giorno_campagna": list(indice) * 2,
        "anno": [str(anno_corrente)] * len(indice) + [str(anno_precedente)] * len(indice),
        "eventi_cumulati": list(serie_corr) + list(serie_prec),
    })

    arch_corr_orari = arch_corr.copy()
    arch_corr_orari["giorno_settimana"] = arch_corr_orari["data_inizio"].dt.dayofweek.map(lambda i: ORDINE_GIORNI[i])
    arch_corr_orari["fascia"] = arch_corr_orari["data_inizio"].dt.hour.map(_fascia_oraria)
    arch_prec_orari = arch_prec.copy()
    arch_prec_orari["giorno_settimana"] = arch_prec_orari["data_inizio"].dt.dayofweek.map(lambda i: ORDINE_GIORNI[i])
    arch_prec_orari["fascia"] = arch_prec_orari["data_inizio"].dt.hour.map(_fascia_oraria)

    return {
        "oggi": oggi,
        "anno_corrente": anno_corrente, "anno_precedente": anno_precedente,
        "inizio_corr": inizio_corr, "fine_corr": fine_corr,
        "inizio_prec": inizio_prec, "fine_prec": fine_prec,
        "tot_corr": tot_corr, "tot_prec": tot_prec, "variazione": variazione,
        "arch_corr": arch_corr, "arch_prec": arch_prec,
        "arch_corr_orari": arch_corr_orari, "arch_prec_orari": arch_prec_orari,
        "df_cum": df_cum,
    }
