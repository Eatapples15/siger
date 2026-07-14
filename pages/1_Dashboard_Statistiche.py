from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

import siger_geocoding
import siger_scraper
import siger_storico

# Palette categorica di riferimento (validata, ordine fisso — vedi skill dataviz)
CATEGORICO = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
SEQUENZIALE_BLU = ["#9ec5f4", "#5598e7", "#256abf", "#104281"]
STATO_COLORI = {"Chiuso": "#0ca30c", "In bonifica": "#fab219", "Aperto": "#d03b3b"}

ORDINE_TIPOLOGIA = [
    "Incendio Boschivo", "Incendio non boschivo", "Incendio Interfaccia",
    "Altro Incendio", "Falso allarme", "Inserimento multiplo",
]
ORDINE_LIVELLO = ["Rischio ordinario", "Rischio Moderato", "Rischio Elevato"]
ORDINE_PROVINCIA = ["PZ", "MT"]
ORDINE_FASCIA = ["Notte (00-06)", "Mattina (06-12)", "Pomeriggio (12-18)", "Sera (18-24)"]
ORDINE_GIORNI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _fascia_oraria(ora: int) -> str:
    if ora < 6:
        return ORDINE_FASCIA[0]
    if ora < 12:
        return ORDINE_FASCIA[1]
    if ora < 18:
        return ORDINE_FASCIA[2]
    return ORDINE_FASCIA[3]


def _mappa_colori_fissa(ordine_fisso, valori_presenti):
    """Colori assegnati per identità (ordine fisso), non per frequenza: una voce
    mantiene sempre lo stesso colore anche cambiando il periodo selezionato."""
    ordine = list(ordine_fisso) + [v for v in valori_presenti if v not in ordine_fisso]
    return {v: CATEGORICO[i % len(CATEGORICO)] for i, v in enumerate(ordine)}


def _conteggio_ordinato(serie: pd.Series, ordine_fisso) -> pd.DataFrame:
    conteggi = serie.fillna("Non specificato").value_counts()
    ordine = list(ordine_fisso) + [v for v in conteggi.index if v not in ordine_fisso]
    conteggi = conteggi.reindex(ordine).dropna()
    df = conteggi.reset_index()
    df.columns = ["voce", "eventi"]
    return df


st.set_page_config(page_title="Dashboard Statistiche - SIGER", layout="wide")
st.title("📊 Dashboard Statistiche Incendi - SIGER")

try:
    siger_username = st.secrets["SIGER_USERNAME"]
    siger_password = st.secrets["SIGER_PASSWORD"]
except KeyError:
    st.error("Credenziali dell'account di servizio SIGER non trovate in .streamlit/secrets.toml.")
    st.stop()

oggi = date.today()
opzione = st.radio("Intervallo", ["Oggi", "Ultima settimana", "Ultimo mese", "Personalizzato"], horizontal=True)
if opzione == "Oggi":
    start_date, end_date = oggi, oggi
elif opzione == "Ultima settimana":
    start_date, end_date = oggi - timedelta(days=7), oggi
elif opzione == "Ultimo mese":
    start_date, end_date = oggi - timedelta(days=30), oggi
else:
    intervallo = st.date_input("Seleziona l'intervallo", [oggi - timedelta(days=7), oggi], max_value=oggi)
    if len(intervallo) != 2:
        st.stop()
    start_date, end_date = intervallo

if st.button("📥 Carica dati", type="primary"):
    log_lines = []
    log_box = st.empty()
    dataset = None
    with st.spinner("🤖 Automazione in corso... login, download ed elaborazione dati."):
        try:
            for msg in siger_scraper.genera_dataset(siger_username, siger_password, start_date, end_date):
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
        siger_storico.upsert_archivio(dataset)
    st.session_state["dashboard_dataset"] = dataset
    st.session_state["dashboard_periodo"] = (start_date, end_date)

dataset = st.session_state.get("dashboard_dataset")
COLONNE_ATTESE = {"fuori_stagione_aib", "possibile_falso_allarme", "numero_mezzi_sistema", "protratto_oltre_24h"}
if dataset is not None and not COLONNE_ATTESE.issubset(dataset.columns):
    # Dataset rimasto in cache da una versione precedente della pipeline (senza le colonne
    # più recenti): scartarlo invece di andare in KeyError più sotto, e chiedere di ricaricare.
    dataset = None
    st.session_state.pop("dashboard_dataset", None)

if dataset is None:
    st.info("Seleziona un intervallo e premi 'Carica dati' per vedere le statistiche.")
    st.stop()
if dataset.empty:
    st.warning("Nessun evento trovato nel periodo selezionato.")
    st.stop()

periodo_start, periodo_end = st.session_state["dashboard_periodo"]
st.caption(f"Periodo: {periodo_start.strftime('%d/%m/%Y')} — {periodo_end.strftime('%d/%m/%Y')} · {len(dataset)} eventi")

# --- KPI ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Eventi totali", len(dataset))
col2.metric("Incendi boschivi", int((dataset["tipologia"] == "Incendio Boschivo").sum()))
col3.metric("Incendi non boschivi", int((dataset["tipologia"] == "Incendio non boschivo").sum()))
tempi_risposta = dataset["tempo_risposta_minuti"].dropna()
col4.metric("Tempo di risposta medio*", f"{tempi_risposta.mean():.0f} min" if len(tempi_risposta) else "n/d")
st.caption(
    "*Stima best-effort ricavata dal testo libero del diario evento: da leggere come "
    "indicazione di massima, non come dato certificato."
)

col5, col6, col7 = st.columns(3)
n_fuori_stagione = int(dataset["fuori_stagione_aib"].fillna(False).sum())
col5.metric("Eventi fuori stagione AIB (1/07–15/09)", n_fuori_stagione)
n_falsi_allarme = int(dataset["possibile_falso_allarme"].sum())
col6.metric("Possibili falsi allarmi**", n_falsi_allarme)
n_protratti = int(dataset["protratto_oltre_24h"].fillna(False).sum())
col7.metric("Incendi protratti oltre 24h", n_protratti)
st.caption(
    "**Individuati cercando la frase 'falso allarme'/'falsa segnalazione' nel diario: nessun "
    "campo strutturato noto per questo dato, quindi il conteggio è indicativo e va verificato."
)

# --- Trend giornaliero ---
st.subheader("Andamento giornaliero")
trend = dataset.dropna(subset=["data_inizio"]).copy()
trend["giorno"] = trend["data_inizio"].dt.normalize()
trend_counts = trend.groupby("giorno").size().reset_index(name="eventi").sort_values("giorno")
# Asse x come stringa (categoriale): con pochi giorni/un solo giorno, un asse data continuo
# di Plotly genera tick con artefatti di precisione float (es. "23:59:59.9996").
trend_counts["giorno_label"] = trend_counts["giorno"].dt.strftime("%d/%m/%Y")
fig_trend = px.bar(trend_counts, x="giorno_label", y="eventi", color_discrete_sequence=[CATEGORICO[0]])
fig_trend.update_layout(xaxis_title="", yaxis_title="Eventi", showlegend=False, xaxis_type="category")
st.plotly_chart(fig_trend, use_container_width=True)

# --- Possibili anomalie ---
st.subheader("Possibili anomalie")
media_giornaliera = trend_counts["eventi"].mean()
std_giornaliera = trend_counts["eventi"].std()
if pd.isna(std_giornaliera) or std_giornaliera == 0:
    st.caption("Periodo troppo corto o uniforme per stimare una soglia di anomalia.")
else:
    soglia = media_giornaliera + 2 * std_giornaliera
    giorni_anomali = trend_counts[trend_counts["eventi"] > soglia][["giorno_label", "eventi"]]
    if giorni_anomali.empty:
        st.caption(f"Nessun giorno oltre la soglia statistica (media + 2 dev. std. = {soglia:.1f} eventi/giorno).")
    else:
        st.write(f"Giorni con eventi oltre la soglia statistica (media + 2 dev. std. = {soglia:.1f}):")
        st.dataframe(giorni_anomali, use_container_width=True, hide_index=True)

comuni_ordinati = dataset.dropna(subset=["data_inizio", "comune"]).sort_values(["comune", "data_inizio"])
pattern_ravvicinati = []
for comune, gruppo in comuni_ordinati.groupby("comune"):
    date_ord = gruppo["data_inizio"].sort_values().tolist()
    if len(date_ord) < 3:
        continue
    for i in range(len(date_ord) - 2):
        finestra_giorni = (date_ord[i + 2] - date_ord[i]).days
        if finestra_giorni <= 5:
            pattern_ravvicinati.append({"comune": comune, "eventi_nel_periodo": len(gruppo), "3_eventi_in_giorni": finestra_giorni})
            break
if pattern_ravvicinati:
    st.write("Comuni con 3+ incendi ravvicinati nel tempo (possibili pattern da verificare):")
    st.dataframe(pd.DataFrame(pattern_ravvicinati), use_container_width=True, hide_index=True)
else:
    st.caption("Nessun comune con 3 o più incendi entro una finestra di 5 giorni nel periodo selezionato.")

# --- Capacità e stress della sala operativa ---
st.subheader("Eventi aperti in concorrenza")
st.caption("Quanti eventi risultano aperti nello stesso giorno: un indicatore diretto di carico sulla sala.")
giorni_periodo = pd.date_range(periodo_start, periodo_end, freq="D")
conteggio_concorrenza = [
    int(((dataset["data_inizio"].dt.date <= g.date()) & (dataset["data_fine"].isna() | (dataset["data_fine"].dt.date >= g.date()))).sum())
    for g in giorni_periodo
]
concorrenza_df = pd.DataFrame({"giorno": giorni_periodo, "eventi_aperti": conteggio_concorrenza})
concorrenza_df["giorno_label"] = concorrenza_df["giorno"].dt.strftime("%d/%m/%Y")
fig_concorrenza = px.bar(concorrenza_df, x="giorno_label", y="eventi_aperti", color_discrete_sequence=[CATEGORICO[0]])
fig_concorrenza.update_layout(xaxis_title="", yaxis_title="Eventi aperti", showlegend=False, xaxis_type="category")
st.plotly_chart(fig_concorrenza, use_container_width=True)
picco = concorrenza_df.loc[concorrenza_df["eventi_aperti"].idxmax()]
st.caption(f"Picco nel periodo: {int(picco['eventi_aperti'])} eventi aperti contemporaneamente il {picco['giorno_label']}.")

st.subheader("Tempo di chiusura nel periodo")
chiusi = dataset.dropna(subset=["data_fine", "durata_minuti"]).copy()
if chiusi.empty:
    st.info("Nessun evento chiuso nel periodo per calcolare il tempo di chiusura.")
else:
    chiusi["giorno"] = chiusi["data_inizio"].dt.normalize()
    durata_media = chiusi.groupby("giorno")["durata_minuti"].mean().reset_index()
    durata_media["giorno_label"] = durata_media["giorno"].dt.strftime("%d/%m/%Y")
    fig_durata = px.line(
        durata_media, x="giorno_label", y="durata_minuti", markers=True,
        color_discrete_sequence=[CATEGORICO[0]],
    )
    fig_durata.update_layout(xaxis_title="", yaxis_title="Durata media (min)", xaxis_type="category")
    st.plotly_chart(fig_durata, use_container_width=True)
    st.caption("Un trend in salita durante la campagna può indicare pressione crescente sulle risorse disponibili.")

# --- Orari di apertura evento ---
st.subheader("Orari di apertura evento")
orari = dataset.dropna(subset=["data_inizio"]).copy()
orari["ora"] = orari["data_inizio"].dt.hour
orari["fascia"] = orari["ora"].map(_fascia_oraria)
orari["giorno_settimana"] = orari["data_inizio"].dt.dayofweek.map(lambda i: ORDINE_GIORNI[i])
granularita = st.radio(
    "Granularità", ["Fascia oraria", "Ora esatta"], horizontal=True, key="granularita_orari"
)
if granularita == "Fascia oraria":
    fascia_counts = _conteggio_ordinato(orari["fascia"], ORDINE_FASCIA)
    fig_orari = px.bar(fascia_counts, x="voce", y="eventi", color_discrete_sequence=[CATEGORICO[0]])
    fig_orari.update_layout(xaxis_title="", yaxis_title="Eventi", showlegend=False)
else:
    ora_counts = orari.groupby("ora").size().reindex(range(24), fill_value=0).reset_index(name="eventi")
    ora_counts["ora_label"] = ora_counts["ora"].map(lambda h: f"{h:02d}:00")
    fig_orari = px.bar(ora_counts, x="ora_label", y="eventi", color_discrete_sequence=[CATEGORICO[0]])
    fig_orari.update_layout(xaxis_title="", yaxis_title="Eventi", showlegend=False, xaxis_type="category")
st.plotly_chart(fig_orari, use_container_width=True)

# --- Per giorno della settimana ---
st.subheader("Per giorno della settimana")
giorno_counts = _conteggio_ordinato(orari["giorno_settimana"], ORDINE_GIORNI)
fig_giorno = px.bar(giorno_counts, x="voce", y="eventi", color_discrete_sequence=[CATEGORICO[0]])
fig_giorno.update_layout(xaxis_title="", yaxis_title="Eventi", showlegend=False)
st.plotly_chart(fig_giorno, use_container_width=True)

# --- Correlazione fascia oraria / dimensione ---
st.subheader("Correlazione orario ed evento")
dimensione_corr = st.selectbox(
    "Confronta la fascia oraria con",
    ["Giorno della settimana", "Provincia", "Tipologia", "Livello di rischio"],
    key="dim_correlazione",
)
colonna_corr = {
    "Giorno della settimana": "giorno_settimana", "Provincia": "provincia",
    "Tipologia": "tipologia", "Livello di rischio": "livello",
}[dimensione_corr]
tabella_corr = pd.crosstab(orari["fascia"], orari[colonna_corr].fillna("Non specificato")).reindex(ORDINE_FASCIA)
if dimensione_corr == "Giorno della settimana":
    tabella_corr = tabella_corr.reindex(columns=ORDINE_GIORNI)
fig_corr = px.imshow(
    tabella_corr, text_auto=True, color_continuous_scale=SEQUENZIALE_BLU, aspect="auto",
    labels=dict(x=dimensione_corr, y="Fascia oraria", color="Eventi"),
)
fig_corr.update_layout(height=350)
st.plotly_chart(fig_corr, use_container_width=True)
st.caption(
    "Esempio di lettura: una cella alta in 'Pomeriggio' × 'Sabato' indica molti incendi "
    "aperti di sabato pomeriggio nel periodo selezionato."
)

# --- Tipologia / Livello / Stato / Provincia ---
col_a, col_b, col_c, col_d = st.columns(4)

with col_a:
    st.subheader("Per tipologia")
    tip_counts = _conteggio_ordinato(dataset["tipologia"], ORDINE_TIPOLOGIA)
    mappa_tip = _mappa_colori_fissa(ORDINE_TIPOLOGIA, tip_counts["voce"])
    fig_tip = px.bar(tip_counts, x="voce", y="eventi", color="voce", color_discrete_map=mappa_tip)
    fig_tip.update_layout(showlegend=False, xaxis_title="", yaxis_title="Eventi")
    st.plotly_chart(fig_tip, use_container_width=True)

with col_b:
    st.subheader("Per livello di rischio")
    liv_counts = _conteggio_ordinato(dataset["livello"], ORDINE_LIVELLO)
    mappa_liv = {v: SEQUENZIALE_BLU[min(i, len(SEQUENZIALE_BLU) - 1)] for i, v in enumerate(liv_counts["voce"])}
    fig_liv = px.bar(liv_counts, x="voce", y="eventi", color="voce", color_discrete_map=mappa_liv)
    fig_liv.update_layout(showlegend=False, xaxis_title="", yaxis_title="Eventi")
    st.plotly_chart(fig_liv, use_container_width=True)

with col_c:
    st.subheader("Per stato")
    stato_counts = _conteggio_ordinato(dataset["stato"], list(STATO_COLORI.keys()))
    fig_stato = px.bar(stato_counts, x="voce", y="eventi", color="voce", color_discrete_map=STATO_COLORI)
    fig_stato.update_layout(showlegend=False, xaxis_title="", yaxis_title="Eventi")
    st.plotly_chart(fig_stato, use_container_width=True)

with col_d:
    st.subheader("Per provincia")
    prov_counts = _conteggio_ordinato(dataset["provincia"], ORDINE_PROVINCIA)
    mappa_prov = _mappa_colori_fissa(ORDINE_PROVINCIA, prov_counts["voce"])
    fig_prov = px.bar(prov_counts, x="voce", y="eventi", color="voce", color_discrete_map=mappa_prov)
    fig_prov.update_layout(showlegend=False, xaxis_title="", yaxis_title="Eventi")
    st.plotly_chart(fig_prov, use_container_width=True)

# --- Comuni più colpiti ---
st.subheader("Comuni più colpiti")
top_n = st.radio("Mostra", [10, 20], horizontal=True, format_func=lambda n: f"Top {n}", key="top_n_comuni")
comuni_counts = (
    dataset["comune"].fillna("Non specificato").value_counts().head(top_n).reset_index()
)
comuni_counts.columns = ["comune", "eventi"]
fig_comuni = px.bar(
    comuni_counts.sort_values("eventi"), x="eventi", y="comune", orientation="h",
    color_discrete_sequence=[CATEGORICO[0]],
)
fig_comuni.update_layout(xaxis_title="Eventi", yaxis_title="", showlegend=False, height=max(300, 24 * top_n))
st.plotly_chart(fig_comuni, use_container_width=True)

# --- Mappa geografica ---
st.subheader("Distribuzione geografica")
st.caption(
    "Le coordinate esatte vengono dal diario evento quando presenti; gli eventi senza "
    "coordinate nel diario sono posizionati in modo approssimato sul comune."
)
with st.spinner("Geocodifica dei comuni senza coordinate precise nel diario..."):
    dataset_geo = siger_geocoding.geocodifica_dataset(dataset)
geo = dataset_geo.dropna(subset=["lat", "lon"])
if geo.empty:
    st.info("Nessun evento di questo periodo è stato posizionabile su una mappa.")
else:
    geo = geo.copy()
    geo["precisione"] = geo["posizione_precisa"].map({True: "Precisa (dal diario)", False: "Approssimata (comune)"})
    geo["dimensione_marker"] = geo["posizione_precisa"].map({True: 14, False: 8})
    mappa_tip_geo = _mappa_colori_fissa(ORDINE_TIPOLOGIA, geo["tipologia"].fillna("Non specificato").unique())
    fig_map = px.scatter_mapbox(
        geo, lat="lat", lon="lon", color="tipologia", color_discrete_map=mappa_tip_geo,
        size="dimensione_marker", size_max=14,
        hover_name="comune",
        hover_data={"id_evento": True, "precisione": True, "lat": False, "lon": False, "dimensione_marker": False},
        zoom=7, height=500, mapbox_style="open-street-map",
    )
    fig_map.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_map, use_container_width=True)
    n_precise = int(geo["posizione_precisa"].sum())
    st.caption(
        f"{len(geo)} eventi su {len(dataset)} posizionati in mappa: {n_precise} con coordinate "
        f"precise dal diario, {len(geo) - n_precise} approssimati sul comune."
    )

    # --- Densità sub-comunale ---
    st.subheader("Densità sub-comunale")
    st.caption(
        "Solo le coordinate precise dal diario: quelle approssimate sul comune si "
        "sovrapporrebbero tutte sullo stesso punto (il centro del paese) e falserebbero la mappa di calore."
    )
    geo_precise = geo[geo["posizione_precisa"]]
    if len(geo_precise) < 2:
        st.info("Servono almeno due eventi con coordinate precise dal diario per mostrare una densità.")
    else:
        fig_densita = px.density_mapbox(
            geo_precise, lat="lat", lon="lon", radius=25,
            hover_name="comune", zoom=7, height=500, mapbox_style="open-street-map",
            color_continuous_scale=SEQUENZIALE_BLU,
        )
        fig_densita.update_layout(margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig_densita, use_container_width=True)
        st.caption(f"{len(geo_precise)} eventi con posizione precisa usati per la mappa di densità.")

# --- Qualità dei dati ---
st.subheader("Qualità dei dati")
col_q1, col_q2, col_q3 = st.columns(3)
pct_coord = 100 * dataset["lat"].notna().mean()
col_q1.metric("Eventi con coordinate precise nel diario", f"{pct_coord:.0f}%")
pct_mezzi = 100 * (dataset["numero_mezzi"] > 0).mean()
col_q2.metric("Eventi con mezzi dichiarati nel diario", f"{pct_mezzi:.0f}%")
confronto_mezzi = dataset.dropna(subset=["numero_mezzi_sistema"])
if confronto_mezzi.empty:
    col_q3.metric("Discrepanze testo vs sistema (mezzi)", "n/d")
else:
    discrepanti = int((confronto_mezzi["numero_mezzi"] != confronto_mezzi["numero_mezzi_sistema"]).sum())
    col_q3.metric("Discrepanze testo vs sistema (mezzi)", f"{discrepanti}/{len(confronto_mezzi)}")
st.caption(
    "Percentuali basse non indicano necessariamente un problema del tool: riflettono quanto "
    "in dettaglio gli operatori compilano il diario."
)

# --- Tabella dettagliata + export ---
st.subheader("Dettaglio eventi")
colonne_tabella = [
    "id_evento", "comune", "provincia", "contesto", "tipologia", "livello", "stato",
    "data_inizio", "data_fine", "durata_minuti", "tempo_risposta_minuti",
    "numero_mezzi", "numero_mezzi_sistema", "fuori_stagione_aib", "possibile_falso_allarme",
    "protratto_oltre_24h",
]
st.dataframe(dataset[colonne_tabella].sort_values("data_inizio", ascending=False), use_container_width=True)

export_df = dataset.drop(columns=["cronologia"]).copy()
export_df["mezzi_elenco"] = export_df["mezzi_elenco"].apply(lambda m: "; ".join(m) if isinstance(m, list) else m)
csv = export_df.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "⬇️ Esporta dataset (CSV)", data=csv,
    file_name=f"eventi_siger_{periodo_start}_{periodo_end}.csv", mime="text/csv",
)
