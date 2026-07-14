"""Archivio storico persistente degli eventi, per il confronto anno-su-anno e per il
recupero di coordinate/mezzi/cronologia di eventi non più coperti dall'export live "Storico"
del portale (che restituisce solo le attività più recenti, senza filtro data: vedi
siger_scraper.scarica_export_storico).

Seed iniziale: foglio 'STORICO' del workbook Excel che la sala operativa mantiene a mano
(REPORTAIB - SALA CONTROLLO.xlsx), normalizzato allo stesso schema del dataset live prodotto
da siger_parser.costruisci_dataset_consolidato. Da lì in avanti l'archivio si arricchisce da
solo: ogni volta che la pipeline live estrae dati dal portale, upsert_archivio() li aggiunge
(deduplicando per id_evento, con priorità ai dati più recenti).

Persistenza remota: il file locale (dati_storici.csv) vive sul filesystem effimero di
Streamlit Cloud, che si azzera ad ogni redeploy/riavvio. Se nei secrets sono presenti
GITHUB_TOKEN/GITHUB_REPO/GITHUB_DATA_BRANCH, l'archivio viene anche letto/scritto da un
branch dati dedicato dello stesso repository (via GitHub Contents API), separato dal branch
di deploy per non causare redeploy. Del tutto opzionale: senza queste credenziali l'archivio
resta solo locale, come prima.
"""
import base64
import json
import logging
from pathlib import Path

import openpyxl
import pandas as pd
import requests

_ARCHIVIO_PATH = Path(__file__).parent / "dati_storici.csv"
_COLONNE_ARCHIVIO = ["id_evento", "comune", "provincia", "contesto", "tipologia", "data_inizio", "data_fine"]
# Campi estratti dal diario evento (siger_parser.estrai_dettagli_diario) che l'export live
# "Storico" può non ricoprire per eventi non recentissimi: persistiti per poter fare da
# fallback nei run successivi (vedi costruisci_dataset_consolidato/archivio_lookup). Gli
# altri campi derivati (numero_mezzi, durata_minuti, tempo_risposta_minuti,
# protratto_oltre_24h, fuori_stagione_aib) non servono qui: si ricalcolano da date/mezzi.
_COLONNE_ARRICCHIMENTO = ["lat", "lon", "mezzi_elenco", "numero_mezzi_sistema", "cronologia", "possibile_falso_allarme"]
_COLONNE_ARCHIVIO_COMPLETO = _COLONNE_ARCHIVIO + _COLONNE_ARRICCHIMENTO
_COLONNE_LISTA = ["mezzi_elenco", "cronologia"]  # richiedono (de)serializzazione JSON per il CSV
_NOME_FILE_GITHUB = "dati_storici.csv"


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
    # L'Excel non contiene i campi di arricchimento estratti dal diario (coordinate/mezzi/
    # cronologia non sono nel foglio STORICO): si aggiungono vuoti per uniformarsi allo
    # schema completo dell'archivio.
    df = df.reindex(columns=_COLONNE_ARCHIVIO_COMPLETO)
    for colonna in _COLONNE_LISTA:
        df[colonna] = [[] for _ in range(len(df))]
    return df


def _deserializza_lista(valore):
    if isinstance(valore, list):
        return valore
    if valore is None or (isinstance(valore, float) and pd.isna(valore)) or valore == "":
        return []
    try:
        return json.loads(valore)
    except (TypeError, json.JSONDecodeError):
        return []


def _config_github(secrets: dict | None):
    if not secrets:
        return None
    token, repo, branch = secrets.get("GITHUB_TOKEN"), secrets.get("GITHUB_REPO"), secrets.get("GITHUB_DATA_BRANCH")
    if not (token and repo and branch):
        return None
    return {"token": token, "repo": repo, "branch": branch}


def _prova_ripristino_da_github(secrets: dict) -> None:
    """Se l'archivio locale non esiste (filesystem effimero riavviato), prova a ripristinarlo
    dal branch dati su GitHub. Best-effort: qualunque errore viene loggato e ignorato, il
    chiamante prosegue con un archivio vuoto come se GitHub non fosse configurato."""
    config = _config_github(secrets)
    if config is None:
        return
    try:
        risposta = requests.get(
            f"https://api.github.com/repos/{config['repo']}/contents/{_NOME_FILE_GITHUB}",
            params={"ref": config["branch"]},
            headers={"Authorization": f"token {config['token']}", "Accept": "application/vnd.github+json"},
            timeout=10,
        )
        if risposta.status_code == 200:
            _ARCHIVIO_PATH.write_bytes(base64.b64decode(risposta.json()["content"]))
    except Exception as e:
        logging.warning("Ripristino dell'archivio storico da GitHub fallito: %s", e)


def _pubblica_su_github(secrets: dict) -> None:
    """Pubblica il CSV locale aggiornato sul branch dati su GitHub. Best-effort: non deve mai
    interrompere la pipeline (stesso principio del fallback LLM in siger_llm.py). Se un altro
    processo ha modificato il file nel frattempo lo sha risulta stale e la PUT fallisce: quel
    run perde solo la persistenza remota, non quella locale (rischio accettato, run a bassa
    frequenza/singolo operatore)."""
    config = _config_github(secrets)
    if config is None:
        return
    try:
        headers = {"Authorization": f"token {config['token']}", "Accept": "application/vnd.github+json"}
        url = f"https://api.github.com/repos/{config['repo']}/contents/{_NOME_FILE_GITHUB}"
        risposta = requests.get(url, params={"ref": config["branch"]}, headers=headers, timeout=10)
        sha_esistente = risposta.json().get("sha") if risposta.status_code == 200 else None

        corpo = {
            "message": "Aggiorna dati_storici.csv",
            "content": base64.b64encode(_ARCHIVIO_PATH.read_bytes()).decode("ascii"),
            "branch": config["branch"],
        }
        if sha_esistente:
            corpo["sha"] = sha_esistente
        requests.put(url, json=corpo, headers=headers, timeout=10).raise_for_status()
    except Exception as e:
        logging.warning("Pubblicazione dell'archivio storico su GitHub fallita: %s", e)


def carica_archivio(secrets: dict | None = None) -> pd.DataFrame:
    if not _ARCHIVIO_PATH.exists() and secrets:
        _prova_ripristino_da_github(secrets)

    if not _ARCHIVIO_PATH.exists():
        return pd.DataFrame(columns=_COLONNE_ARCHIVIO_COMPLETO)

    df = pd.read_csv(_ARCHIVIO_PATH, parse_dates=["data_inizio", "data_fine"])
    # reindex: retrocompatibile con CSV scritti dalla vecchia versione a 7 colonne (senza i
    # campi di arricchimento) — le colonne mancanti vengono aggiunte vuote.
    df = df.reindex(columns=_COLONNE_ARCHIVIO_COMPLETO)
    for colonna in _COLONNE_LISTA:
        df[colonna] = df[colonna].apply(_deserializza_lista)
    return df


def upsert_archivio(nuovi_eventi: pd.DataFrame, secrets: dict | None = None) -> pd.DataFrame:
    """Unisce nuovi_eventi con l'archivio su disco, deduplicando per id_evento (tiene la
    versione più recente — i dati passati per ultimi in ordine di concatenazione vincono,
    quindi qui i dati live sovrascrivono quelli storici per gli id in comune). Salva
    localmente e, se secrets contiene le credenziali GitHub, pubblica anche sul branch dati
    remoto (best-effort). Restituisce l'archivio aggiornato con le liste già deserializzate."""
    if nuovi_eventi.empty:
        return carica_archivio(secrets)

    esistente = carica_archivio(secrets)
    colonne_presenti = [c for c in _COLONNE_ARCHIVIO_COMPLETO if c in nuovi_eventi.columns]
    nuovi = nuovi_eventi[colonne_presenti].reindex(columns=_COLONNE_ARCHIVIO_COMPLETO).copy()
    for colonna in _COLONNE_LISTA:
        nuovi[colonna] = nuovi[colonna].apply(lambda v: v if isinstance(v, list) else [])

    combinato = nuovi if esistente.empty else pd.concat([esistente, nuovi], ignore_index=True)
    combinato = combinato.drop_duplicates(subset="id_evento", keep="last")
    combinato = combinato.sort_values("id_evento").reset_index(drop=True)

    da_salvare = combinato.copy()
    for colonna in _COLONNE_LISTA:
        da_salvare[colonna] = da_salvare[colonna].apply(lambda v: json.dumps(v, ensure_ascii=False))
    da_salvare.to_csv(_ARCHIVIO_PATH, index=False)

    if secrets:
        _pubblica_su_github(secrets)

    return combinato
