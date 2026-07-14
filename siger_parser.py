"""Parsing degli export SIGER (formato Excel 2003 XML/SpreadsheetML, estensione .xls)
e costruzione del dataset consolidato per-evento.

Le funzioni qui dentro sono pure (nessuna dipendenza da Playwright/rete) e possono
essere testate direttamente sui file scaricati manualmente dal portale.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pandas as pd

_NS = "{urn:schemas-microsoft-com:office:spreadsheet}"
_CONTESTI_PATH = Path(__file__).parent / "contesti_basilicata.csv"
_FALSO_ALLARME_TIPOLOGIE = {"falso allarme"}

_MESI_EN = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_DATA_RE = re.compile(
    r"(?P<mese>[A-Za-z]{3})\s+(?P<giorno>\d{1,2}),\s+(?P<anno>\d{4}),\s+"
    r"(?P<ora>\d{1,2}):(?P<minuto>\d{2})\s+(?P<meridiem>AM|PM)"
)

_LOCALITA_RE = re.compile(r"^(?P<comune>.*?)\s+(?P<provincia>[A-Z]{2}),\s*(?P<indirizzo>.*?)\s*-\s*\d+\s*$")

_COORDINATE_RE = re.compile(
    r"coord(?:inate)?\.?\s*(?:gps)?\s*:?\s*(-?\d{1,3}\.\d{3,})\s*[,;-]?\s+(-?\d{1,3}\.\d{3,})",
    re.IGNORECASE,
)
# Formato gradi/primi/secondi (es. 40°58'07.9"N 15°49'43.1"E): non richiede la parola
# "coordinate" davanti, perché la sintassi ° ' " N/S/E/W è già inequivocabile da sola —
# utile anche perché in pratica non tutte le note usano lo stesso termine introduttivo.
_COORDINATE_DMS_RE = re.compile(
    r"(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:[.,]\d+)?)\s*\"?\s*([NS])\s*[,;]?\s+"
    r"(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:[.,]\d+)?)\s*\"?\s*([EW])",
    re.IGNORECASE,
)
_MEZZO_RE = re.compile(
    r"\b((?i:CdB|boschiva|ordinaria|DOS))\s+(?:d[i']\s+)?"
    r"([A-ZÀ-Ù][\w'\-]*(?:\s+[A-ZÀ-Ù][\w'\-]*){0,2})"
)
_MEZZO_CANONICO = {"cdb": "CdB", "boschiva": "boschiva", "ordinaria": "ordinaria", "dos": "DOS"}
_MEZZI_SISTEMA_RE = re.compile(r"Mezzi attualmente associati all'evento\s+(\d+)", re.IGNORECASE)
_TIMELINE_RE = re.compile(
    # L'ancoraggio a inizio riga (^|\n) evita di scambiare per un nuovo evento in cronologia
    # un riferimento a un orario dentro la prosa (es. "...riferisce che alle ore 08:29...").
    r"(?:^|\n)\s*ore\s+(\d{1,2}[:.]\d{2})\s*-?\s*(.+?)(?=\n\s*ore\s+\d{1,2}[:.]\d{2}\b|\Z)",
    re.DOTALL | re.IGNORECASE | re.MULTILINE,
)
_INVIO_RE = re.compile(r"\b(invia|invio|attiv|part[ei])", re.IGNORECASE)


def _dms_a_decimale(gradi: str, primi: str, secondi: str, direzione: str) -> float:
    decimale = float(gradi) + float(primi) / 60 + float(secondi.replace(",", ".")) / 3600
    return -decimale if direzione.upper() in ("S", "W") else decimale


def _estrai_coordinate(testo: str):
    """Prova prima il formato gradi/primi/secondi (es. 40°58'07.9"N), poi quello decimale
    (es. 'coordinate 40.30, 16.65'): nel diario si trovano entrambi indistintamente."""
    m = _COORDINATE_DMS_RE.search(testo)
    if m:
        lat_g, lat_p, lat_s, lat_dir, lon_g, lon_p, lon_s, lon_dir = m.groups()
        return (
            _dms_a_decimale(lat_g, lat_p, lat_s, lat_dir),
            _dms_a_decimale(lon_g, lon_p, lon_s, lon_dir),
        )
    m = _COORDINATE_RE.search(testo)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def _ripara_mojibake(testo: str) -> str:
    """Corregge il doppio-encoding UTF-8 (es. 'localitÃ ' invece di 'località') che
    a volte compare nel testo libero esportato dal portale. 'Ã' isolata è un
    segnale affidabile di doppio-encoding, quindi il tentativo di riparazione
    scatta solo in quel caso e viene scartato se non produce testo valido."""
    if "Ã" not in testo:
        return testo
    try:
        return testo.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return testo


def _parse_rows(source) -> list[dict[int, str]]:
    """Legge un export SIGER in formato Excel-2003-XML e restituisce una lista
    di righe, ciascuna un dict {indice_colonna: testo_cella}."""
    root = ET.parse(source).getroot()
    rows = []
    for row_el in root.iter(f"{_NS}Row"):
        row = {}
        col = 0
        for cell_el in row_el.findall(f"{_NS}Cell"):
            idx_attr = cell_el.get(f"{_NS}Index")
            col = int(idx_attr) if idx_attr is not None else col + 1
            data_el = cell_el.find(f"{_NS}Data")
            testo = data_el.text if data_el is not None and data_el.text else ""
            row[col] = _ripara_mojibake(testo)
        rows.append(row)
    return rows


def _parse_data_ora(testo):
    testo = (testo or "").strip()
    if not testo:
        return None
    m = _DATA_RE.match(testo)
    if not m:
        return None
    mese = _MESI_EN.get(m.group("mese")[:3].title())
    if mese is None:
        return None
    ora = int(m.group("ora")) % 12
    if m.group("meridiem").upper() == "PM":
        ora += 12
    return datetime(int(m.group("anno")), mese, int(m.group("giorno")), ora, int(m.group("minuto")))


def _trova_intestazione(rows, prima_colonna="Id Evento"):
    return next((i for i, r in enumerate(rows) if r.get(1) == prima_colonna), None)


def parse_eventi_export(source) -> pd.DataFrame:
    """Parsa l'export 'Reportistica > Report per data' (EVENTIDAA): un evento per riga."""
    rows = _parse_rows(source)
    header_idx = _trova_intestazione(rows)
    if header_idx is None:
        raise ValueError("Intestazione 'Id Evento' non trovata nell'export eventi.")

    records = []
    for r in rows[header_idx + 1:]:
        id_evento = (r.get(1) or "").strip()
        if not id_evento.isdigit():
            continue
        records.append({
            "id_evento": int(id_evento),
            "localita": (r.get(3) or "").strip(),
            "data_inizio": _parse_data_ora(r.get(4)),
            "data_fine": _parse_data_ora(r.get(5)),
            "stato": (r.get(6) or "").strip(),
            "livello": (r.get(7) or "").strip(),
            "tipologia": (r.get(8) or "").strip(),
        })

    df = pd.DataFrame.from_records(records)
    if df.empty:
        return df

    loc = df["localita"].str.extract(_LOCALITA_RE)
    df["comune"] = loc["comune"]
    df["provincia"] = loc["provincia"]
    df["indirizzo"] = loc["indirizzo"]
    return df


def filtra_per_intervallo(df_eventi: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """Filtro di sicurezza lato codice sulla data di apertura evento: il portale non sempre
    applica correttamente il filtro data richiesto nella UI e può restituire un insieme più
    ampio di eventi (es. gli ultimi N di default). Va applicato subito dopo il parsing
    dell'export eventi, prima di qualunque uso a valle (report/dashboard)."""
    if df_eventi.empty:
        return df_eventi
    data_apertura = df_eventi["data_inizio"].dt.date
    dentro_intervallo = data_apertura.notna() & (data_apertura >= start_date) & (data_apertura <= end_date)
    return df_eventi[dentro_intervallo].reset_index(drop=True)


def parse_storico_export(source) -> pd.DataFrame:
    """Parsa l'export 'Reportistica > Storico' (STORICOEVENTI): il registro attività/diario."""
    rows = _parse_rows(source)
    header_idx = _trova_intestazione(rows)
    if header_idx is None:
        raise ValueError("Intestazione 'Id Evento' non trovata nell'export storico.")

    records = []
    for r in rows[header_idx + 1:]:
        id_evento = (r.get(1) or "").strip()
        if not id_evento.isdigit():
            continue
        records.append({
            "id_evento": int(id_evento),
            "data_ora": _parse_data_ora(r.get(3)),
            "operazione": (r.get(4) or "").strip(),
            "attivita": r.get(5) or "",
        })
    return pd.DataFrame.from_records(records)


def estrai_dettagli_diario(testo: str) -> dict:
    """Estrae coordinate GPS, mezzi/squadre attivati e cronologia da una nota diario.

    Estrazione best-effort su testo libero scritto dagli operatori: i campi possono
    mancare o essere incompleti a seconda di come è stata redatta la nota.
    """
    testo = testo or ""

    lat, lon = _estrai_coordinate(testo)

    mezzi_grezzi = [
        f"{_MEZZO_CANONICO.get(tipo.lower(), tipo)} di {luogo.strip()}"
        for tipo, luogo in _MEZZO_RE.findall(testo)
    ]
    if re.search(r"elicottero\s*:\s*presente", testo, re.IGNORECASE):
        mezzi_grezzi.append("Elicottero")
    if re.search(r"aereo\s*:\s*presente", testo, re.IGNORECASE):
        mezzi_grezzi.append("Aereo")
    mezzi = list(dict.fromkeys(mezzi_grezzi))  # unità distinte, ordine di prima citazione

    cronologia_grezza = [
        (ora.replace(".", ":"), desc.strip(" \n\t-"))
        for ora, desc in _TIMELINE_RE.findall(testo)
    ]
    cronologia = list(dict.fromkeys(cronologia_grezza))  # rimuove i duplicati (stessa voce ripetuta tra revisioni)

    # Campo di sistema ("Mezzi attualmente associati all'evento N"): più affidabile del
    # conteggio da testo libero, utile come controllo incrociato.
    match_sistema = _MEZZI_SISTEMA_RE.search(testo)
    numero_mezzi_sistema = int(match_sistema.group(1)) if match_sistema else None

    # Nessun campo strutturato noto per i falsi allarmi: euristica sul testo, da verificare.
    possibile_falso_allarme = bool(re.search(r"falso\s+allarme|falsa\s+segnalazione", testo, re.IGNORECASE))

    return {
        "lat": lat, "lon": lon, "mezzi": mezzi, "cronologia": cronologia,
        "numero_mezzi_sistema": numero_mezzi_sistema,
        "possibile_falso_allarme": possibile_falso_allarme,
    }


def _carica_contesti() -> dict:
    """Mappa (comune normalizzato, provincia) -> nome contesto, dall'anagrafica comuni
    del workbook Excel della sala operativa (vedi contesti_basilicata.csv, estratto una
    tantum dal foglio 'DATI')."""
    if not _CONTESTI_PATH.exists():
        return {}
    df = pd.read_csv(_CONTESTI_PATH)
    return {
        (str(r["comune"]).strip().casefold(), str(r["provincia"]).strip().upper()): r["contesto_nome"]
        for _, r in df.iterrows()
    }


_CONTESTI = _carica_contesti()


def _contesto_di(comune, provincia):
    if comune is None or provincia is None or pd.isna(comune) or pd.isna(provincia):
        return None
    chiave = (str(comune).strip().casefold(), str(provincia).strip().upper())
    return _CONTESTI.get(chiave)


def _e_falso_allarme_strutturato(tipologia) -> bool:
    """'Falso allarme' è un valore ufficiale del campo Tipologia (confermato nel foglio DATI
    e nello storico della sala operativa), anche se non l'ho mai visto nei campioni live
    finora — probabilmente perché è raro (~1.6% degli eventi nello storico)."""
    if tipologia is None or (isinstance(tipologia, float) and pd.isna(tipologia)):
        return False
    return str(tipologia).strip().casefold() in _FALSO_ALLARME_TIPOLOGIE


_AIB_INIZIO = (7, 1)   # 1 luglio
_AIB_FINE = (9, 15)    # 15 settembre


def _fuori_stagione_aib(data_inizio) -> bool | None:
    """True se l'evento è aperto fuori dalla campagna AIB (1 luglio - 15 settembre)."""
    if data_inizio is None or pd.isna(data_inizio):
        return None
    mese_giorno = (data_inizio.month, data_inizio.day)
    return not (_AIB_INIZIO <= mese_giorno <= _AIB_FINE)


def _tempo_risposta_minuti(data_inizio, cronologia):
    """Stima (best-effort) i minuti tra l'apertura evento e il primo invio di una
    squadra/mezzo citato nel diario. Restituisce None quando non è deducibile."""
    if data_inizio is None or pd.isna(data_inizio) or not cronologia:
        return None
    for ora_str, descrizione in cronologia:
        if not _INVIO_RE.search(descrizione):
            continue
        try:
            ora, minuto = (int(x) for x in ora_str.split(":"))
        except ValueError:
            continue
        istante = data_inizio.replace(hour=ora, minute=minuto, second=0, microsecond=0)
        delta_minuti = (istante - data_inizio).total_seconds() / 60
        if -180 <= delta_minuti <= 180:
            return round(delta_minuti)
    return None


def costruisci_dataset_consolidato(
    df_eventi: pd.DataFrame, df_storico: pd.DataFrame, enrichment_fallback=None, archivio_lookup=None
) -> pd.DataFrame:
    """Unisce i dati strutturati dell'evento (EVENTIDAA) con i dettagli estratti dal diario
    (STORICOEVENTI): coordinate, mezzi impiegati, cronologia e tempi derivati.

    Le note vengono aggregate su TUTTE le righe MODIFICA EVENTO/INSERIMENTO EVENTO di un
    evento, non solo sull'ultima: un dettaglio (es. le coordinate) spesso viene scritto in
    una nota iniziale e non ripetuto nei successivi aggiornamenti, quindi guardare solo
    l'ultima nota lo perderebbe.

    Per ogni evento si tenta, in ordine (solo finché le coordinate mancano): 1) le regex su
    df_storico (gratuito, istantaneo); 2) archivio_lookup, se fornito (id_evento -> dict di
    campi già noti da un run precedente — gratuito, istantaneo: l'export live "Storico" del
    portale non supporta un filtro data e restituisce solo le attività più recenti, quindi
    per eventi non recentissimi le regex qui sopra spesso non trovano nulla anche se erano
    già state estratte in un giorno precedente); 3) enrichment_fallback, se fornito (funzione
    testo -> dict|None, tipicamente un LLM: vedi siger_llm.crea_fallback — ultima spiaggia,
    unico tentativo con un costo). Questo modulo non fa mai accesso a rete/disco da sé:
    archivio_lookup ed enrichment_fallback sono passati già pronti dal chiamante."""
    if df_eventi.empty:
        return df_eventi

    testo_per_evento = {}
    if not df_storico.empty:
        # Nessun filtro sul tipo di operazione: oltre a MODIFICA EVENTO/INSERIMENTO EVENTO
        # anche CHIUSURA EVENTO porta note narrative complete, e altri tipi (GESTIONE MEZZO,
        # ATTIVAZIONE STRATEGIA...) contengono solo "Utente: NOME" quindi non fanno danno se
        # inclusi — aggregare tutto è più robusto che dover elencare ogni tipo conosciuto.
        storico_ordinato = df_storico.sort_values("data_ora")
        for id_evento, gruppo in storico_ordinato.groupby("id_evento"):
            testo_per_evento[id_evento] = "\n".join(gruppo["attivita"].fillna(""))

    dettagli_per_evento = {}
    # Si itera su TUTTI gli eventi del report, non solo su quelli con righe nello storico
    # scaricato: un evento assente da df_storico (diario troppo vecchio per l'export live)
    # deve comunque poter ricevere il testo vuoto e provare archivio_lookup/enrichment_fallback,
    # non essere saltato del tutto.
    for id_evento in df_eventi["id_evento"].unique():
        testo_completo = testo_per_evento.get(id_evento, "")
        dettagli = estrai_dettagli_diario(testo_completo)

        if dettagli["lat"] is None and archivio_lookup is not None:
            pregresso = archivio_lookup.get(id_evento)
            if pregresso and pregresso.get("lat") is not None:
                dettagli["lat"] = pregresso.get("lat")
                dettagli["lon"] = pregresso.get("lon")
                if not dettagli["mezzi"] and pregresso.get("mezzi_elenco"):
                    dettagli["mezzi"] = pregresso["mezzi_elenco"]
                if not dettagli["cronologia"] and pregresso.get("cronologia"):
                    dettagli["cronologia"] = pregresso["cronologia"]
                if dettagli["numero_mezzi_sistema"] is None and pregresso.get("numero_mezzi_sistema") is not None:
                    dettagli["numero_mezzi_sistema"] = pregresso["numero_mezzi_sistema"]
                dettagli["possibile_falso_allarme"] = (
                    dettagli["possibile_falso_allarme"] or bool(pregresso.get("possibile_falso_allarme"))
                )

        # LLM solo quando né le regex né l'archivio hanno trovato le coordinate: è il caso
        # che le regex gestiscono peggio (formati non ancora visti), mentre mezzi/cronologia
        # sono già estratti in modo affidabile nella maggioranza dei casi.
        if enrichment_fallback is not None and dettagli["lat"] is None:
            extra = enrichment_fallback(testo_completo)
            if extra:
                if dettagli["lat"] is None:
                    dettagli["lat"] = extra.get("lat")
                    dettagli["lon"] = extra.get("lon")
                if not dettagli["mezzi"] and extra.get("mezzi"):
                    dettagli["mezzi"] = extra["mezzi"]
                dettagli["possibile_falso_allarme"] = (
                    dettagli["possibile_falso_allarme"] or extra.get("possibile_falso_allarme", False)
                )
        dettagli_per_evento[id_evento] = dettagli

    df = df_eventi.copy()
    df["lat"] = df["id_evento"].map(lambda i: dettagli_per_evento.get(i, {}).get("lat"))
    df["lon"] = df["id_evento"].map(lambda i: dettagli_per_evento.get(i, {}).get("lon"))
    df["mezzi_elenco"] = df["id_evento"].map(lambda i: dettagli_per_evento.get(i, {}).get("mezzi", []))
    df["numero_mezzi"] = df["mezzi_elenco"].map(len)
    df["numero_mezzi_sistema"] = df["id_evento"].map(lambda i: dettagli_per_evento.get(i, {}).get("numero_mezzi_sistema"))
    df["cronologia"] = df["id_evento"].map(lambda i: dettagli_per_evento.get(i, {}).get("cronologia", []))
    # 'Falso allarme' come valore ufficiale del campo Tipologia (quando presente) è
    # autoritativo; l'euristica sul testo del diario resta come fallback per i casi in cui
    # non è così classificato a livello di campo ma lo si intuisce dalle note.
    df["possibile_falso_allarme"] = df.apply(
        lambda r: _e_falso_allarme_strutturato(r.get("tipologia"))
        or dettagli_per_evento.get(r["id_evento"], {}).get("possibile_falso_allarme", False),
        axis=1,
    )
    df["fuori_stagione_aib"] = df["data_inizio"].map(_fuori_stagione_aib)
    df["contesto"] = df.apply(lambda r: _contesto_di(r.get("comune"), r.get("provincia")), axis=1)

    df["durata_minuti"] = df.apply(
        lambda r: round((r["data_fine"] - r["data_inizio"]).total_seconds() / 60)
        if pd.notna(r["data_inizio"]) and pd.notna(r["data_fine"]) else None,
        axis=1,
    )
    df["tempo_risposta_minuti"] = df.apply(
        lambda r: _tempo_risposta_minuti(r["data_inizio"], r["cronologia"]), axis=1
    )
    df["protratto_oltre_24h"] = df.apply(
        lambda r: _protratto_oltre_24h(r["data_inizio"], r["data_fine"]), axis=1
    )

    return df


def _protratto_oltre_24h(data_inizio, data_fine):
    """True se l'evento dura (o ha durato) più di 24 ore. Per gli eventi ancora aperti
    (data_fine mancante) confronta con l'istante corrente."""
    if data_inizio is None or pd.isna(data_inizio):
        return None
    riferimento = data_fine if (data_fine is not None and pd.notna(data_fine)) else pd.Timestamp.now()
    return (riferimento - data_inizio).total_seconds() >= 24 * 3600


def eventi_carryover(df: pd.DataFrame, giorno) -> pd.DataFrame:
    """Eventi aperti PRIMA del giorno indicato ma ancora rilevanti in quel giorno (non ancora
    chiusi, o chiusi proprio in quel giorno): il caso "gestito oggi ma aperto ieri o prima".
    Richiede che df copra anche i giorni precedenti (query con una finestra più ampia del
    solo giorno da riepilogare)."""
    if df.empty:
        return df
    aperti_prima = df["data_inizio"].dt.date < giorno
    ancora_rilevanti = df["data_fine"].isna() | (df["data_fine"].dt.date >= giorno)
    return df[aperti_prima & ancora_rilevanti]
