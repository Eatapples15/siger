"""Estrazione via LLM (Claude) come fallback quando le regex di siger_parser.py non
trovano le coordinate GPS nel testo libero del diario evento.

Isolato in un modulo a parte (anziché dentro siger_parser.py) per non introdurre una
dipendenza di rete in quel modulo, che resta puro/testabile offline. La regex resta il
metodo primario di estrazione (veloce, gratuito, già affidabile nella maggioranza dei
casi): l'LLM viene interpellato solo per gli eventi in cui le regex non hanno trovato le
coordinate, non per ogni evento.
"""
import json
import logging

import anthropic

_MODEL = "claude-haiku-4-5"

_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": ["number", "null"], "description": "Latitudine decimale, o null se non presente nel testo."},
        "lon": {"type": ["number", "null"], "description": "Longitudine decimale, o null se non presente nel testo."},
        "mezzi": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Mezzi/squadre antincendio citati nel testo, es. 'CdB di Potenza', 'Elicottero'.",
        },
        "possibile_falso_allarme": {"type": "boolean"},
    },
    "required": ["lat", "lon", "mezzi", "possibile_falso_allarme"],
    "additionalProperties": False,
}

_SYSTEM = (
    "Estrai informazioni strutturate dal testo libero di un diario evento di un incendio "
    "boschivo/non boschivo, scritto da operatori di una sala operativa di Protezione Civile. "
    "Le coordinate GPS possono comparire in formato gradi/primi/secondi (es. 40°58'07.9\"N "
    "15°49'43.1\"E) o decimale (es. 40.30, 16.65), con o senza la parola 'coordinate' davanti. "
    "I mezzi/squadre possono essere nominati in modi diversi (es. 'CdB di Potenza', 'squadra "
    "boschiva di Matera', 'DOS di ...', 'Elicottero'). Restituisci null/lista vuota per i "
    "campi non presenti nel testo: non inventare né dedurre valori non scritti esplicitamente."
)


def estrai_dettagli_llm(testo: str, api_key: str | None = None) -> dict | None:
    """Fallback via LLM per estrarre coordinate/mezzi/falso-allarme da una nota diario.

    Restituisce None (mai un'eccezione) se manca la chiave API, la chiamata fallisce o la
    risposta non è utilizzabile: essendo un fallback opzionale, un suo errore non deve mai
    interrompere la pipeline, che può sempre proseguire con i soli risultati delle regex.
    """
    if not testo or not testo.strip():
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[{"role": "user", "content": testo}],
        )
    except Exception as e:  # fallback best-effort: qualunque errore non deve propagarsi
        logging.warning("Fallback LLM per estrazione diario fallito: %s", e)
        return None

    testo_json = next((b.text for b in response.content if b.type == "text"), None)
    if not testo_json:
        return None
    try:
        dati = json.loads(testo_json)
    except json.JSONDecodeError:
        return None

    return {
        "lat": dati.get("lat"),
        "lon": dati.get("lon"),
        "mezzi": dati.get("mezzi") or [],
        "possibile_falso_allarme": bool(dati.get("possibile_falso_allarme")),
    }


def crea_fallback(api_key: str | None):
    """Costruisce la closure testo -> dict|None da passare come enrichment_fallback a
    siger_parser.costruisci_dataset_consolidato. Restituisce None se non è disponibile una
    chiave API: in quel caso l'estrazione resta esclusivamente basata su regex."""
    if not api_key:
        return None

    def _fallback(testo: str) -> dict | None:
        return estrai_dettagli_llm(testo, api_key=api_key)

    return _fallback
