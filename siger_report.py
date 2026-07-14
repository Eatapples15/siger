"""Generazione del report PDF giornaliero a partire dal dataset consolidato
prodotto da siger_parser.costruisci_dataset_consolidato.
"""
import html
from datetime import date

import pandas as pd
from playwright.sync_api import sync_playwright

_STILE = """
body { font-family: Arial, sans-serif; font-size: 12px; color: #222; }
h2 { margin-bottom: 2px; }
.sottotitolo { color: #666; margin-top: 0; }
table { width: 100%; border-collapse: collapse; margin-top: 16px; }
th, td { border: 1px solid #ddd; text-align: left; padding: 6px; vertical-align: top; }
th { background-color: #f2f2f2; }
table.riepilogo { width: auto; min-width: 260px; }
.footer { margin-top: 24px; font-size: 10px; color: grey; }
"""


def _fmt_data_ora(dt) -> str:
    return dt.strftime("%d/%m %H:%M") if dt is not None and not pd.isna(dt) else "-"


def _fmt_mezzi(mezzi) -> str:
    return html.escape(", ".join(mezzi)) if mezzi else "-"


def _tabella_riepilogo(df: pd.DataFrame, colonna: str, titolo: str) -> str:
    conteggi = df[colonna].fillna("Non specificato").value_counts()
    righe = "".join(
        f"<tr><td>{html.escape(str(voce))}</td><td>{n}</td></tr>"
        for voce, n in conteggi.items()
    )
    return f"""<table class="riepilogo"><tr><th colspan="2">{titolo}</th></tr>{righe}
        <tr><td><b>Totale</b></td><td><b>{len(df)}</b></td></tr></table>"""


def _tabella_dettaglio(df: pd.DataFrame) -> str:
    if df.empty:
        return "<p>Nessun evento nel periodo selezionato.</p>"
    intestazione = (
        "<tr><th>Id</th><th>Comune</th><th>Tipologia</th><th>Livello</th>"
        "<th>Stato</th><th>Apertura</th><th>Chiusura</th><th>Mezzi impiegati</th></tr>"
    )
    righe = []
    for _, r in df.sort_values("data_inizio", ascending=False).iterrows():
        righe.append(
            "<tr>"
            f"<td>{r['id_evento']}</td>"
            f"<td>{html.escape(str(r.get('comune') or '-'))} ({html.escape(str(r.get('provincia') or '-'))})</td>"
            f"<td>{html.escape(str(r.get('tipologia') or '-'))}</td>"
            f"<td>{html.escape(str(r.get('livello') or '-'))}</td>"
            f"<td>{html.escape(str(r.get('stato') or '-'))}</td>"
            f"<td>{_fmt_data_ora(r.get('data_inizio'))}</td>"
            f"<td>{_fmt_data_ora(r.get('data_fine'))}</td>"
            f"<td>{_fmt_mezzi(r.get('mezzi_elenco'))}</td>"
            "</tr>"
        )
    return f"<table>{intestazione}{''.join(righe)}</table>"


def _tabella_carryover(df: pd.DataFrame, giorno: date) -> str:
    if df.empty:
        return "<p>Nessun incendio proveniente dai giorni precedenti ancora in corso.</p>"
    intestazione = (
        "<tr><th>Id</th><th>Comune</th><th>Tipologia</th><th>Stato</th>"
        "<th>Aperto dal</th><th>Giorni aperto</th></tr>"
    )
    righe = []
    for _, r in df.sort_values("data_inizio").iterrows():
        giorni_aperto = (giorno - r["data_inizio"].date()).days
        righe.append(
            "<tr>"
            f"<td>{r['id_evento']}</td>"
            f"<td>{html.escape(str(r.get('comune') or '-'))} ({html.escape(str(r.get('provincia') or '-'))})</td>"
            f"<td>{html.escape(str(r.get('tipologia') or '-'))}</td>"
            f"<td>{html.escape(str(r.get('stato') or '-'))}</td>"
            f"<td>{_fmt_data_ora(r.get('data_inizio'))}</td>"
            f"<td>{giorni_aperto}</td>"
            "</tr>"
        )
    return f"<table>{intestazione}{''.join(righe)}</table>"


def _lancia_chromium(p):
    """Prova prima il Chromium di sistema (installato via apt da packages.txt, il caso di
    Streamlit Community Cloud), poi il Chromium gestito da Playwright (installato in locale
    con 'playwright install chromium')."""
    try:
        return p.chromium.launch(headless=True, channel="chromium")
    except Exception:
        return p.chromium.launch(headless=True)


def _renderizza_pdf(html_pdf: str) -> bytes:
    """Converte HTML in PDF. Non richiede una sessione autenticata sul portale: apre un
    browser headless a parte, usato solo come motore di rendering."""
    with sync_playwright() as p:
        browser = _lancia_chromium(p)
        try:
            page = browser.new_page()
            page.set_content(html_pdf)
            return page.pdf(format="A4", print_background=True, margin={"top": "20px", "bottom": "20px"})
        finally:
            browser.close()


def genera_pdf_giornaliero(
    df_eventi: pd.DataFrame, giorno: date, username: str, eventi_carryover: pd.DataFrame | None = None
) -> bytes:
    """Renderizza il report PDF del giorno.

    df_eventi: eventi aperti nel giorno stesso. eventi_carryover (opzionale): eventi aperti
    in giorni precedenti ma ancora in corso/rilevanti nel giorno (vedi
    siger_parser.eventi_carryover) — mostrati in una sezione separata, non nei conteggi
    principali per non falsare le statistiche del giorno."""
    generato_il = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M:%S")

    sezione_carryover = ""
    if eventi_carryover is not None:
        sezione_carryover = f"""
        <h3>Incendi aperti da più giorni (ancora in corso)</h3>
        <p class="sottotitolo">Aperti prima del {giorno.strftime('%d/%m/%Y')} e non ancora chiusi</p>
        {_tabella_carryover(eventi_carryover, giorno)}"""

    html_pdf = f"""<html><head><style>{_STILE}</style></head><body>
        <h2>Riepilogo Incendi del {giorno.strftime('%d/%m/%Y')}</h2>
        <p class="sottotitolo">Eventi gestiti dalla sala operativa nella giornata</p>
        {_tabella_riepilogo(df_eventi, 'tipologia', 'Per tipologia')}
        {_tabella_riepilogo(df_eventi, 'livello', 'Per livello di rischio')}
        {_tabella_dettaglio(df_eventi)}
        {sezione_carryover}
        <div class="footer">Report generato il {generato_il} con l'utente Siger: {html.escape(username)}</div>
        </body></html>"""

    return _renderizza_pdf(html_pdf)


def genera_pdf_settimanale(
    df_eventi: pd.DataFrame, inizio: date, fine: date, username: str, totale_settimana_precedente: int | None = None
) -> bytes:
    """Renderizza il report PDF della settimana (per la cabina di regia del martedì).

    totale_settimana_precedente (opzionale): totale eventi della settimana precedente preso
    dall'archivio storico locale (siger_storico), per il confronto settimana-su-settimana."""
    generato_il = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M:%S")

    sezione_confronto = ""
    if totale_settimana_precedente is not None:
        variazione_testo = ""
        if totale_settimana_precedente > 0:
            variazione = round(100 * (len(df_eventi) - totale_settimana_precedente) / totale_settimana_precedente, 1)
            segno = "+" if variazione > 0 else ""
            variazione_testo = f" ({segno}{variazione}% rispetto alla settimana precedente)"
        sezione_confronto = f"""<p class="sottotitolo">Settimana precedente: {totale_settimana_precedente} eventi{variazione_testo}</p>"""

    html_pdf = f"""<html><head><style>{_STILE}</style></head><body>
        <h2>Riepilogo Incendi settimanale — {inizio.strftime('%d/%m/%Y')} → {fine.strftime('%d/%m/%Y')}</h2>
        <p class="sottotitolo">Eventi gestiti dalla sala operativa nella settimana</p>
        {sezione_confronto}
        {_tabella_riepilogo(df_eventi, 'tipologia', 'Per tipologia')}
        {_tabella_riepilogo(df_eventi, 'livello', 'Per livello di rischio')}
        {_tabella_dettaglio(df_eventi)}
        <div class="footer">Report generato il {generato_il} con l'utente Siger: {html.escape(username)}</div>
        </body></html>"""

    return _renderizza_pdf(html_pdf)
