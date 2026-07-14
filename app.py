import asyncio
import base64
from datetime import datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components
import telegram

import siger_bot
import siger_parser
import siger_report
import siger_scraper
import siger_storico

GIORNI_LOOKBACK_CARRYOVER = 7  # per intercettare incendi aperti nei giorni precedenti e ancora in corso


def scarica_automaticamente(pdf_bytes: bytes, filename: str):
    """Avvia il download del PDF senza bisogno di un click aggiuntivo: un link nascosto con
    'download' viene cliccato via JS. st.components.v1.html esegue davvero lo script (a
    differenza di st.markdown, che inserisce l'HTML senza eseguire i <script> al suo interno).
    Niente più anteprima incorporata: su Streamlit Cloud un iframe annidato per il PDF va in
    conflitto col sandboxing dell'iframe della piattaforma stessa (anteprima bianca)."""
    base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f"""
    <a id="link" href="data:application/pdf;base64,{base64_pdf}" download="{filename}"></a>
    <script>document.getElementById('link').click();</script>
    """
    components.html(html, height=0)


async def _invia_documento_telegram(bot_token, chat_id, pdf_bytes, filename, caption):
    bot = telegram.Bot(token=bot_token)
    async with bot:
        await bot.send_document(chat_id=chat_id, document=pdf_bytes, filename=filename, caption=caption)


def send_telegram_report(pdf_bytes, giorno):
    try:
        bot_token = st.secrets["TELEGRAM_BOT_TOKEN"]
        chat_id = st.secrets["TELEGRAM_CHAT_ID"]
    except KeyError:
        st.error("Credenziali Telegram (Bot Token, Chat ID) non trovate nei secrets.")
        return

    caption = f"📄 Report Siger del {giorno.strftime('%d/%m/%Y')}"
    try:
        # python-telegram-bot v20+ è interamente asincrono: bot.send_document() da sola
        # crea una coroutine senza eseguirla, quindi va eseguita con asyncio.run().
        asyncio.run(_invia_documento_telegram(
            bot_token, chat_id, pdf_bytes, f"Report_Siger_{giorno.strftime('%Y%m%d')}.pdf", caption,
        ))
        st.success("Report inviato con successo alla chat di Telegram!")
    except Exception as e:
        st.error(f"Errore durante l'invio del messaggio su Telegram: {e}")


st.set_page_config(page_title="Report Siger", layout="centered")
st.title("📄 Report Giornaliero Incendi - SIGER")
st.write("Genera il report degli eventi (incendi boschivi e non boschivi) gestiti dalla sala operativa nella giornata odierna.")

try:
    siger_username = st.secrets["SIGER_USERNAME"]
    siger_password = st.secrets["SIGER_PASSWORD"]
except KeyError:
    st.error(
        "Credenziali dell'account di servizio SIGER non trovate in "
        ".streamlit/secrets.toml (chiavi SIGER_USERNAME / SIGER_PASSWORD)."
    )
    st.stop()

try:
    # Fa partire il bot Telegram (/report) come thread di background di questo stesso
    # processo: su Streamlit Community Cloud non si può eseguire un secondo processo
    # indipendente (siger_bot.py standalone), quindi lo incorporiamo qui. dict(st.secrets)
    # perché su Streamlit Cloud è l'unica fonte affidabile per i Secrets configurati sulla
    # piattaforma. Sicuro da richiamare ad ogni rerun: il guardiano è dentro siger_bot stesso.
    siger_bot.avvia_bot_in_background_una_volta(dict(st.secrets))
except Exception as e:
    st.sidebar.warning(f"Bot Telegram non avviato: {e}")


def _esegui_pipeline_live(inizio, fine):
    """Esegue login + estrazione con spinner e log a schermo, restituendo il dataset
    consolidato. In caso di errore mostra il messaggio e ferma lo script (st.stop)."""
    dataset = None
    log_lines = []
    log_box = st.empty()
    with st.spinner("🤖 Automazione in corso... login, download ed elaborazione dati."):
        try:
            for msg in siger_scraper.genera_dataset(
                siger_username, siger_password, inizio, fine, secrets=dict(st.secrets),
            ):
                if isinstance(msg, str):
                    if msg.startswith("dataset:"):
                        continue
                    log_lines.append(msg.strip())
                    log_box.text("\n".join(log_lines))
                else:
                    dataset = msg
        except RuntimeError as e:
            st.error(str(e))
            st.stop()
    if dataset is not None and not dataset.empty:
        siger_storico.upsert_archivio(dataset, secrets=dict(st.secrets))
    return dataset


invia_telegram = st.checkbox("Invia il report su Telegram al termine")

col_giorno, col_settimana = st.columns(2)

if col_giorno.button("🚀 Genera report di oggi", type="primary"):
    oggi = datetime.now().date()
    # Finestra allargata (non solo oggi): un incendio aperto ieri e ancora in corso ha data
    # di apertura di ieri, quindi una query filtrata solo su "oggi" non lo troverebbe. Il
    # filtro sul giorno vero e proprio avviene sotto.
    dataset = _esegui_pipeline_live(oggi - timedelta(days=GIORNI_LOOKBACK_CARRYOVER), oggi)

    if dataset is None or dataset.empty:
        st.warning("Nessun evento trovato per la giornata odierna.")
    else:
        eventi_oggi = dataset[dataset["data_inizio"].dt.date == oggi]
        carryover = siger_parser.eventi_carryover(dataset, oggi)
        if eventi_oggi.empty:
            st.warning("Nessun evento aperto oggi (potrebbero comunque esserci incendi dei giorni precedenti ancora in corso, vedi PDF).")
        pdf_bytes = siger_report.genera_pdf_giornaliero(eventi_oggi, oggi, siger_username, eventi_carryover=carryover)
        st.success(f"✅ Report generato: {len(eventi_oggi)} eventi di oggi, {len(carryover)} ancora in corso dai giorni precedenti.")
        nome_file = f"Report_Siger_{oggi.strftime('%Y%m%d')}.pdf"
        scarica_automaticamente(pdf_bytes, nome_file)
        st.download_button(
            label="⬇️ Scarica di nuovo il PDF",
            data=pdf_bytes,
            file_name=f"Report_Siger_{oggi.strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )
        if invia_telegram:
            with st.spinner("Invio del report su Telegram..."):
                send_telegram_report(pdf_bytes, oggi)

if col_settimana.button("📅 Genera report settimanale"):
    oggi = datetime.now().date()
    inizio_settimana = oggi - timedelta(days=6)
    dataset_sett = _esegui_pipeline_live(inizio_settimana, oggi)

    if dataset_sett is None or dataset_sett.empty:
        st.warning("Nessun evento trovato per la settimana.")
    else:
        # Confronto con la settimana precedente: preso dall'archivio storico locale (non
        # richiede una seconda query al portale) se già presente.
        archivio = siger_storico.carica_archivio(dict(st.secrets))
        totale_precedente = None
        if not archivio.empty:
            inizio_prec = inizio_settimana - timedelta(days=7)
            fine_prec = oggi - timedelta(days=7)
            maschera = archivio["data_inizio"].dt.date.between(inizio_prec, fine_prec)
            totale_precedente = int(maschera.sum())
        pdf_bytes_sett = siger_report.genera_pdf_settimanale(
            dataset_sett, inizio_settimana, oggi, siger_username, totale_precedente
        )
        st.success(f"✅ Report settimanale generato: {len(dataset_sett)} eventi.")
        nome_file_sett = f"Report_Siger_settimanale_{inizio_settimana.strftime('%Y%m%d')}_{oggi.strftime('%Y%m%d')}.pdf"
        scarica_automaticamente(pdf_bytes_sett, nome_file_sett)
        st.download_button(
            label="⬇️ Scarica di nuovo il PDF settimanale",
            data=pdf_bytes_sett,
            file_name=nome_file_sett,
            mime="application/pdf",
        )
        if invia_telegram:
            with st.spinner("Invio del report su Telegram..."):
                send_telegram_report(pdf_bytes_sett, oggi)
