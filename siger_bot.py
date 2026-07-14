"""Bot Telegram: risponde al comando /report generando e inviando su richiesta il PDF del
report giornaliero.

Due modi d'uso:
1. Standalone: `python siger_bot.py`, resta in ascolto finché non lo fermi (Ctrl+C).
2. Incorporato nell'app Streamlit: app.py chiama avvia_bot_in_background_una_volta(), che
   fa partire il polling in un thread di background del processo Streamlit stesso — utile
   per Streamlit Community Cloud, dove non si può eseguire un secondo processo indipendente.

Le credenziali: in uso standalone si leggono da .streamlit/secrets.toml (tomllib); incorporate
in Streamlit si passano da app.py (già lette via st.secrets, l'unica fonte affidabile su
Streamlit Community Cloud — lì i Secrets configurati sulla piattaforma non è garantito siano
anche un file fisico in quel percorso al momento giusto)."""
import asyncio
import threading
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import siger_parser
import siger_report
import siger_scraper
import siger_storico

# Pulsanti sotto ogni messaggio del bot: più immediati dei comandi digitati per chi usa
# il bot occasionalmente. "callback_data" identifica l'azione, non è testo visibile.
_TASTIERA_PRINCIPALE = InlineKeyboardMarkup([
    [InlineKeyboardButton("📄 Report di oggi", callback_data="report")],
    [InlineKeyboardButton("❓ Guida", callback_data="help")],
])

# Comandi mostrati nel menu nativo di Telegram (icona "/" accanto al campo di scrittura).
_COMANDI_BOT = [
    BotCommand("report", "Genera e invia il report di oggi (PDF)"),
    BotCommand("help", "Mostra la guida"),
    BotCommand("start", "Messaggio di benvenuto e guida"),
]

GIORNI_LOOKBACK_CARRYOVER = 7
_SECRETS_PATH = Path(__file__).parent / ".streamlit" / "secrets.toml"


def _carica_secrets() -> dict:
    with open(_SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def _chat_id_autorizzati_da_secrets(secrets: dict) -> set:
    """Chat autorizzate a chiedere /report: TELEGRAM_CHAT_ID (una, storica) più l'eventuale
    TELEGRAM_CHAT_IDS (elenco aggiuntivo) per autorizzare altri account/gruppi senza perdere
    quello già configurato. TELEGRAM_CHAT_IDS è accettato sia come stringa separata da
    virgole ("123,456") sia come lista TOML (["123", "456"]) — entrambe le sintassi sono
    naturali da scrivere nei secrets, quindi si accettano entrambe invece di richiederne
    una specifica in modo silenzioso."""
    autorizzati = set()
    if secrets.get("TELEGRAM_CHAT_ID"):
        autorizzati.add(str(secrets["TELEGRAM_CHAT_ID"]).strip())

    chat_ids_extra = secrets.get("TELEGRAM_CHAT_IDS", "")
    grezzi = chat_ids_extra if isinstance(chat_ids_extra, list) else str(chat_ids_extra).split(",")
    for cid in grezzi:
        cid = str(cid).strip()
        if cid:
            autorizzati.add(cid)
    return autorizzati


def _genera_report_oggi_sync(secrets: dict):
    """Esegue la pipeline live (sincrona, Playwright) e restituisce (pdf_bytes, n_oggi,
    n_carryover). pdf_bytes è None se non ci sono eventi. Eseguita in un thread separato
    (vedi asyncio.to_thread sotto) per non bloccare il loop asincrono del bot."""
    username, password = secrets["SIGER_USERNAME"], secrets["SIGER_PASSWORD"]
    oggi = datetime.now().date()
    dataset = None
    for msg in siger_scraper.genera_dataset(
        username, password, oggi - timedelta(days=GIORNI_LOOKBACK_CARRYOVER), oggi, secrets=secrets,
    ):
        if not isinstance(msg, str):
            dataset = msg

    if dataset is None or dataset.empty:
        return None, 0, 0

    siger_storico.upsert_archivio(dataset, secrets=secrets)
    eventi_oggi = dataset[dataset["data_inizio"].dt.date == oggi]
    carryover = siger_parser.eventi_carryover(dataset, oggi)
    pdf_bytes = siger_report.genera_pdf_giornaliero(eventi_oggi, oggi, username, eventi_carryover=carryover)
    return pdf_bytes, len(eventi_oggi), len(carryover)


async def _rispondi_report(message, context: ContextTypes.DEFAULT_TYPE, chat_id: str):
    """Logica di /report, condivisa tra il comando testuale e il pulsante "📄 Report di
    oggi": message è update.message (da CommandHandler) o update.callback_query.message
    (dal pulsante) — entrambi espongono reply_text/reply_document con la stessa firma."""
    if chat_id not in context.bot_data["chat_id_autorizzati"]:
        await message.reply_text(
            f"⛔ Non sei autorizzato a richiedere report da questo bot.\n"
            f"Il tuo chat id è {chat_id}: se deve essere autorizzato, aggiungilo a "
            f"TELEGRAM_CHAT_IDS in .streamlit/secrets.toml."
        )
        return

    await message.reply_text(
        "🤖 Generazione del report in corso (di solito 30-60 secondi: mi collego al portale "
        "SIGER e scarico i dati)..."
    )
    secrets = context.bot_data["secrets"]
    try:
        pdf_bytes, n_oggi, n_carryover = await asyncio.to_thread(_genera_report_oggi_sync, secrets)
    except RuntimeError as e:
        await message.reply_text(f"❌ Errore durante la generazione del report:\n{e}")
        return
    except Exception as e:
        await message.reply_text(f"❌ Errore imprevisto durante la generazione del report: {e}")
        return

    if pdf_bytes is None:
        await message.reply_text("Nessun evento trovato per la giornata odierna.", reply_markup=_TASTIERA_PRINCIPALE)
        return

    oggi = datetime.now().date()
    await message.reply_document(
        document=pdf_bytes,
        filename=f"Report_Siger_{oggi.strftime('%Y%m%d')}.pdf",
        caption=(
            f"📄 Report del {oggi.strftime('%d/%m/%Y')}: {n_oggi} eventi di oggi, "
            f"{n_carryover} ancora in corso dai giorni precedenti."
        ),
        reply_markup=_TASTIERA_PRINCIPALE,
    )


async def comando_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _rispondi_report(update.message, context, str(update.effective_chat.id))


async def gestisci_pulsante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce il tap sui pulsanti inline (callback_data "report"/"help")."""
    query = update.callback_query
    await query.answer()  # toglie la clessidra di caricamento sul pulsante in Telegram
    chat_id = str(update.effective_chat.id)
    if query.data == "report":
        await _rispondi_report(query.message, context, chat_id)
    elif query.data == "help":
        await query.message.reply_text(_TESTO_GUIDA, parse_mode="Markdown", reply_markup=_TASTIERA_PRINCIPALE)


_TESTO_GUIDA = (
    "👋 Ciao! Sono il bot del sistema SIGER per il report giornaliero incendi della sala "
    "operativa — Protezione Civile Regione Basilicata.\n\n"
    "Usa i *pulsanti* qui sotto, oppure scrivi il comando corrispondente:\n\n"
    "📄 *Report di oggi* (o /report) — genera e invia il PDF con gli incendi gestiti dalla "
    "sala operativa oggi: elenco eventi, tipologia, livello di rischio, mezzi impiegati, e "
    "gli incendi aperti nei giorni precedenti ancora in corso.\n"
    "❓ *Guida* (o /help) — mostra di nuovo questo messaggio.\n\n"
    "⏱️ *Quanto ci vuole*: circa 30-60 secondi (mi collego al portale SIGER e scarico i "
    "dati) — appena chiedi il report ricevi subito una conferma che ho iniziato, poi il PDF "
    "quando è pronto. Non serve fare altro nel frattempo.\n\n"
    "🔒 *Chi può usarmi*: solo le chat autorizzate da chi gestisce il tool (vedi "
    "TELEGRAM_CHAT_ID/TELEGRAM_CHAT_IDS nella configurazione). Se richiedi un report e non "
    "sei autorizzato, ti mostro il tuo chat id da comunicare a chi gestisce il tool per "
    "essere aggiunto."
)


async def comando_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_TESTO_GUIDA, parse_mode="Markdown", reply_markup=_TASTIERA_PRINCIPALE)


async def comando_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(_TESTO_GUIDA, parse_mode="Markdown", reply_markup=_TASTIERA_PRINCIPALE)


async def _al_avvio(app: Application):
    """post_init: registra i comandi nel menu nativo di Telegram (icona "/" accanto al
    campo di scrittura), una volta sola all'avvio del bot."""
    await app.bot.set_my_commands(_COMANDI_BOT)


def _costruisci_app(secrets: dict) -> Application:
    chat_id_autorizzati = _chat_id_autorizzati_da_secrets(secrets)

    app = Application.builder().token(secrets["TELEGRAM_BOT_TOKEN"]).post_init(_al_avvio).build()
    app.bot_data["secrets"] = secrets
    app.bot_data["chat_id_autorizzati"] = chat_id_autorizzati
    app.add_handler(CommandHandler("start", comando_start))
    app.add_handler(CommandHandler("help", comando_help))
    app.add_handler(CommandHandler("report", comando_report))
    app.add_handler(CallbackQueryHandler(gestisci_pulsante))
    return app


def main():
    """Avvio standalone: `python siger_bot.py`. Gestisce Ctrl+C normalmente perché gira
    nel thread principale. Legge le credenziali dal file locale .streamlit/secrets.toml."""
    secrets = _carica_secrets()
    app = _costruisci_app(secrets)
    print(f"Bot avviato. Chat autorizzate a richiedere report: {app.bot_data['chat_id_autorizzati']}")
    app.run_polling()


_bot_lock = threading.Lock()
_bot_thread = None
_bot_errore = None


def _esegui_polling_in_thread(secrets: dict):
    global _bot_errore
    try:
        app = _costruisci_app(secrets)
        print(f"[siger_bot] Avviato in background. Chat autorizzate: {app.bot_data['chat_id_autorizzati']}")
        # stop_signals=None: i signal handler (Ctrl+C, SIGTERM) si possono installare solo
        # nel thread principale del processo — qui siamo in un thread secondario.
        app.run_polling(stop_signals=None)
    except Exception as e:
        _bot_errore = str(e)
        print(f"[siger_bot] Errore, bot non avviato: {e}")


def avvia_bot_in_background_una_volta(secrets: dict):
    """Avvia il bot in un thread di background, una sola volta per processo. Sicura da
    chiamare ad ogni rerun di Streamlit (il guardiano è a livello di modulo: dato che
    Python importa un modulo una sola volta per processo, le chiamate successive nello
    stesso processo la trovano già "vista" e non fanno nulla).

    secrets: passato dal chiamante (app.py, via st.secrets) invece di essere riletto da file,
    perché su Streamlit Community Cloud i Secrets configurati sulla piattaforma sono
    affidabili solo tramite st.secrets."""
    global _bot_thread
    with _bot_lock:
        if _bot_thread is not None:
            return
        _bot_thread = threading.Thread(
            target=_esegui_polling_in_thread, args=(secrets,), daemon=True, name="siger-telegram-bot"
        )
        _bot_thread.start()


if __name__ == "__main__":
    main()
