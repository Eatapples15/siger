"""Automazione Playwright per il portale SIGER: login e download degli export
'Report per data' (EVENTIDAA) e 'Storico' (STORICOEVENTI) consumati da siger_parser.

Nota: i selettori della sezione Reportistica sono stati ricostruiti solo da
screenshot, non verificati sul DOM live del portale. Se un passaggio fallisce,
viene salvato uno screenshot di debug e sollevato un errore esplicito invece di
proseguire silenziosamente con dati potenzialmente non filtrati/sbagliati.
"""
import io
import re
from datetime import date, datetime

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

import siger_parser
import siger_playwright

URL_LOGIN = "https://siger.regione.basilicata.it/sau/views/contents/login/login.xhtml"
URL_STORICO = "https://siger.regione.basilicata.it/sistemagestionerischi/views/contents/storico/index.xhtml"


def login(page: Page, username: str, password: str):
    page.goto(URL_LOGIN, wait_until="networkidle")
    page.fill("input[id='formLogin:username']", username)
    page.fill("input[id='formLogin:password']", password)
    page.click("a[id='formLogin:loginButton']")
    page.wait_for_load_state("networkidle")

    siger_label_selector = "label:has-text('SIGER')"
    try:
        page.wait_for_selector(siger_label_selector, timeout=5000)
        page.click(siger_label_selector)
        enter_button_selector = "a:has-text('ENTRA')"
        page.wait_for_selector(enter_button_selector)
        page.click(enter_button_selector)
        page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        pass  # nessuna pagina intermedia di selezione app/ruolo: già in dashboard


def _scarica_export_xls(page: Page, screenshot_path: str) -> bytes:
    """Clicca il link di export 'XLS' nella pagina corrente e cattura il file scaricato."""
    try:
        with page.expect_download(timeout=30000) as download_info:
            page.click("a:has-text('XLS')")
        download = download_info.value
        with open(download.path(), "rb") as f:
            return f.read()
    except PlaywrightTimeoutError as e:
        page.screenshot(path=screenshot_path)
        raise RuntimeError(
            "Impossibile scaricare l'export XLS: il link 'XLS' non ha avviato un "
            f"download entro il timeout. Screenshot salvato in {screenshot_path}."
        ) from e


def _clicca_voce_menu(page: Page, testo_tradotto: str, chiave_i18n: str, timeout: int = 15000):
    """Clicca una voce di menu individuandola sia per il testo italiano tradotto sia per
    la chiave i18n grezza (il portale a volte non risolve il bundle di traduzione e mostra
    '???chiave???' invece dell'etichetta: vedi genera_dataset per il tentativo di fix a monte)."""
    pattern = re.compile(rf"{re.escape(testo_tradotto)}|{re.escape(chiave_i18n)}", re.IGNORECASE)
    page.get_by_text(pattern).first.click(timeout=timeout)


def _parse_data_flessibile(testo: str):
    """Converte in date un testo dd/mm/yyyy o dd-mm-yyyy (il separatore mostrato dal
    calendario può variare)."""
    for formato in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(testo.strip(), formato).date()
        except ValueError:
            continue
    return None


def _seleziona_data_calendario(page: Page, campo, target: date, oggi: date):
    """Imposta una data cliccando sul popup calendario invece di scrivere testo nel campo:
    digitare direttamente il testo lo mostra nell'input ma il portale lo marca come non
    valido (bordo rosso) e la ricerca risulta vuota, quindi il valore va selezionato
    davvero dal calendario come farebbe un utente."""
    icona = campo.locator("xpath=following-sibling::*[1]")
    icona.click()
    pannello = page.locator(".ui-datepicker").first
    pannello.wait_for(state="visible", timeout=10000)

    # Il calendario si apre di default sul mese corrente: calcoliamo quanti mesi navigare
    # avanti/indietro dalla differenza di mesi, senza dover leggere/interpretare il nome
    # del mese mostrato (che dipende dalla lingua del widget).
    delta_mesi = (target.year - oggi.year) * 12 + (target.month - oggi.month)
    freccia = ".ui-datepicker-next" if delta_mesi > 0 else ".ui-datepicker-prev"
    for _ in range(abs(delta_mesi)):
        pannello.locator(freccia).click()
        page.wait_for_timeout(150)

    giorno_cella = pannello.locator("td:not(.ui-datepicker-other-month) a", has_text=re.compile(rf"^{target.day}$"))
    giorno_cella.first.click()


def scarica_export_eventi(page: Page, start_date: date, end_date: date) -> bytes:
    """Naviga su 'Reportistica > Report per data', imposta l'intervallo e scarica l'export XLS.

    La pagina mostra prima un menu a tendina 'Tipologia di Ricerca': solo dopo aver scelto
    l'opzione per intervallo compaiono i campi data."""
    _clicca_voce_menu(page, "REPORTISTICA", "menusx.reportistica")
    _clicca_voce_menu(page, "Report per data", "reportEvento.ricercaPerData")
    page.wait_for_load_state("networkidle")

    # 'Tipologia di Ricerca' è un widget PrimeFaces (selectOneMenu): il <select> nativo
    # esiste nel DOM ma è nascosto e non è collegato all'evento che rivela i campi data.
    # Va aperto come farebbe un utente: click sull'etichetta visibile, poi sull'opzione.
    # I campi data compaiono via AJAX dopo aver scelto l'opzione, con un ritardo non legato
    # al networkidle: usiamo wait_for su un elemento reale (auto-retry) invece di un count()
    # istantaneo, che in un paio di tentativi ha dato falsi negativi per pura questione di tempi.
    etichetta_da = page.get_by_text("Data Apertura Evento (da)").first
    try:
        page.click("#tipologiaRicerca_label")
        opzione_intervallo_loc = page.locator("#tipologiaRicerca_panel").get_by_text(
            re.compile("intervallo", re.IGNORECASE)
        ).first
        opzione_intervallo_loc.wait_for(state="visible", timeout=10000)
        opzione_intervallo_loc.click()
        etichetta_da.wait_for(state="visible", timeout=15000)
    except PlaywrightTimeoutError as e:
        page.screenshot(path="debug_report_per_data_filtro.png")
        raise RuntimeError(
            "Selezionata la tipologia di ricerca per intervallo, ma i campi 'Data Apertura "
            "Evento (da)/(a)' non sono comparsi entro il timeout. Screenshot salvato in "
            "debug_report_per_data_filtro.png: serve verificare insieme com'è fatto quel controllo."
        ) from e

    # I campi si trovano cercando il primo <input> dopo ciascuna etichetta visibile (via
    # get_by_text, che risolve all'elemento più specifico invece che a un antenato generico:
    # una xpath grezza con contains(text(), ...) non trovava nulla perché l'etichetta è
    # probabilmente avvolta in un elemento figlio, non testo diretto).
    campo_da = etichetta_da.locator("xpath=following::input[1]")
    campo_a = page.get_by_text("Data Apertura Evento (a)").first.locator("xpath=following::input[1]")
    oggi = date.today()
    _seleziona_data_calendario(page, campo_da, start_date, oggi)
    _seleziona_data_calendario(page, campo_a, end_date, oggi)

    # Controllo preciso: rileggiamo il valore effettivo dei campi invece di fidarci che il
    # click sul calendario sia stato registrato. Se qualcosa non ha funzionato (es. giorno
    # non trovato/cliccato nel mese sbagliato) meglio fermarsi qui che inviare una RICERCA
    # sbagliata in silenzio e restituire dati di un periodo diverso da quello richiesto.
    # Il confronto è tollerante al separatore (il widget può mostrare "-" invece di "/").
    valore_da = _parse_data_flessibile(campo_da.input_value())
    valore_a = _parse_data_flessibile(campo_a.input_value())
    if valore_da != start_date or valore_a != end_date:
        page.screenshot(path="debug_date_non_confermate.png")
        raise RuntimeError(
            f"Dopo la selezione dal calendario le date non corrispondono a quelle richieste: "
            f"'da' è '{campo_da.input_value()}' → {valore_da} (atteso {start_date}), "
            f"'a' è '{campo_a.input_value()}' → {valore_a} (atteso {end_date}). Screenshot "
            "salvato in debug_date_non_confermate.png: la RICERCA non è stata inviata per "
            "evitare di scaricare dati di un periodo sbagliato."
        )

    ricerca_button = page.locator("button:has-text('RICERCA'), a:has-text('RICERCA'), input[value='RICERCA']")
    if ricerca_button.count() == 0:
        page.screenshot(path="debug_ricerca_non_trovata.png")
        raise RuntimeError(
            "Non ho trovato il pulsante RICERCA dopo aver compilato le date. Screenshot "
            "salvato in debug_ricerca_non_trovata.png: la query non è stata inviata."
        )
    ricerca_button.first.click()
    page.wait_for_load_state("networkidle")
    # Diagnostica: la tabella a schermo dopo la ricerca, per capire se il problema è nella
    # query (mostra già solo oggi qui) o nell'export XLS (mostra il periodo giusto, ma il
    # file scaricato no).
    page.screenshot(path="debug_dopo_ricerca.png")

    return _scarica_export_xls(page, "debug_export_eventi_error.png")


def scarica_export_storico(page: Page) -> bytes:
    """Naviga su 'Reportistica > Storico' e scarica l'export XLS (registro attività)."""
    page.goto(URL_STORICO, wait_until="networkidle")
    return _scarica_export_xls(page, "debug_export_storico_error.png")


def genera_dataset(username: str, password: str, start_date: date, end_date: date):
    """Generator: fa login una volta, scarica entrambi gli export e restituisce (via
    'yield') messaggi di log e infine il DataFrame consolidato (chiave 'dataset:')."""
    with sync_playwright() as p:
        browser = siger_playwright.lancia_chromium(p)
        context = browser.new_context(
            ignore_https_errors=True,
            accept_downloads=True,
            locale="it-IT",
            extra_http_headers={"Accept-Language": "it-IT,it;q=0.9"},
        )
        page = context.new_page()

        try:
            yield "log: Login al portale SIGER...\n"
            login(page, username, password)

            yield "log: Download export eventi (Report per data)...\n"
            bytes_eventi = scarica_export_eventi(page, start_date, end_date)

            yield "log: Download export storico (registro attività)...\n"
            bytes_storico = scarica_export_storico(page)

            yield "log: Parsing ed elaborazione dati...\n"
            df_eventi = siger_parser.parse_eventi_export(io.BytesIO(bytes_eventi))
            n_scaricati = len(df_eventi)
            df_eventi = siger_parser.filtra_per_intervallo(df_eventi, start_date, end_date)
            if n_scaricati != len(df_eventi):
                yield (
                    f"log: Attenzione: il portale ha restituito {n_scaricati} eventi, "
                    f"{len(df_eventi)} dei quali nell'intervallo richiesto (filtro data "
                    "applicato lato codice come controllo di sicurezza).\n"
                )
            df_storico = siger_parser.parse_storico_export(io.BytesIO(bytes_storico))
            dataset = siger_parser.costruisci_dataset_consolidato(df_eventi, df_storico)

            yield "dataset:"
            yield dataset
        except RuntimeError:
            raise  # già corredato di screenshot e messaggio chiaro da _scarica_export_xls/le funzioni sopra
        except PlaywrightTimeoutError as e:
            page.screenshot(path="debug_timeout_error.png")
            raise RuntimeError(
                "Timeout durante l'automazione: un elemento atteso non è comparso in tempo. "
                "Screenshot salvato in debug_timeout_error.png."
            ) from e
        except Exception as e:
            page.screenshot(path="debug_unexpected_error.png")
            raise RuntimeError(
                f"Errore imprevisto durante l'automazione: {e}. "
                "Screenshot salvato in debug_unexpected_error.png."
            ) from e
        finally:
            context.close()
            browser.close()
