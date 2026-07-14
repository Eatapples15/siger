from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

import siger_storico

CATEGORICO = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
ORDINE_TIPOLOGIA = [
    "Incendio Boschivo", "Incendio non boschivo", "Incendio Interfaccia",
    "Altro Incendio", "Falso allarme", "Inserimento multiplo",
]


def _mappa_colori_fissa(ordine_fisso, valori_presenti):
    ordine = list(ordine_fisso) + [v for v in valori_presenti if v not in ordine_fisso]
    return {v: CATEGORICO[i % len(CATEGORICO)] for i, v in enumerate(ordine)}


def _dentro_finestra(data_inizio, mm_dd_i, mm_dd_f) -> bool:
    md = (data_inizio.month, data_inizio.day)
    return (mm_dd_i.month, mm_dd_i.day) <= md <= (mm_dd_f.month, mm_dd_f.day)


st.set_page_config(page_title="Confronto Storico - SIGER", layout="wide")
st.title("📈 Confronto Storico Anno-su-Anno - SIGER")

with st.expander("Importa/aggiorna l'archivio storico da file Excel"):
    st.caption(
        "Carica il workbook 'REPORTAIB - SALA CONTROLLO.xlsx' (foglio 'STORICO') per "
        "(ri)popolare l'archivio storico locale. Da qui in poi l'archivio si aggiorna anche "
        "automaticamente ogni volta che generi un report/dashboard con dati live (vedi "
        "siger_storico.upsert_archivio)."
    )
    file_excel = st.file_uploader("Workbook Excel", type=["xlsx"])
    if file_excel is not None and st.button("Importa storico"):
        with st.spinner("Importazione in corso..."):
            nuovi = siger_storico.importa_storico_excel(file_excel)
            archivio_aggiornato = siger_storico.upsert_archivio(nuovi)
        st.success(f"Archivio aggiornato: {len(archivio_aggiornato)} eventi totali.")

archivio = siger_storico.carica_archivio()
if archivio.empty:
    st.info("Nessun dato storico in archivio. Importa il workbook Excel qui sopra per iniziare.")
    st.stop()

archivio = archivio.dropna(subset=["data_inizio"])
anni_disponibili = sorted(archivio["data_inizio"].dt.year.unique())
st.caption(f"Archivio: {len(archivio)} eventi · anni disponibili: {', '.join(map(str, anni_disponibili))}")

# --- Confronto stessa finestra tra anni ---
st.subheader("Confronto stessa finestra tra anni")
st.caption(
    "Replica il confronto 'a pari data' già in uso (es. dal 1/7 ad oggi, per ogni anno "
    "disponibile) — solo giorno e mese contano, l'anno del selettore viene ignorato."
)
oggi = date.today()
col1, col2 = st.columns(2)
mm_dd_inizio = col1.date_input("Inizio finestra", date(oggi.year, 7, 1))
mm_dd_fine = col2.date_input("Fine finestra", oggi)

archivio_finestra = archivio[archivio["data_inizio"].apply(lambda d: _dentro_finestra(d, mm_dd_inizio, mm_dd_fine))]

per_anno = archivio_finestra.groupby(archivio_finestra["data_inizio"].dt.year).size().reindex(anni_disponibili, fill_value=0)
tabella_anni = per_anno.reset_index()
tabella_anni.columns = ["anno", "eventi"]
tabella_anni["variazione_%"] = tabella_anni["eventi"].pct_change().mul(100).round(1)

fig_anni = px.bar(tabella_anni, x="anno", y="eventi", color_discrete_sequence=[CATEGORICO[0]])
fig_anni.update_layout(xaxis_title="", yaxis_title="Eventi", showlegend=False, xaxis_type="category")
st.plotly_chart(fig_anni, use_container_width=True)
st.dataframe(tabella_anni, use_container_width=True)

# --- Per tipologia, anno su anno ---
st.subheader("Per tipologia, anno su anno")
tabella_tipologia = pd.crosstab(archivio_finestra["data_inizio"].dt.year, archivio_finestra["tipologia"])
tabella_tipologia = tabella_tipologia.reindex(index=anni_disponibili, fill_value=0)
mappa_tip = _mappa_colori_fissa(ORDINE_TIPOLOGIA, tabella_tipologia.columns)
fig_tip = px.bar(tabella_tipologia, barmode="group", color_discrete_map=mappa_tip)
fig_tip.update_layout(xaxis_title="", yaxis_title="Eventi", xaxis_type="category", legend_title="")
st.plotly_chart(fig_tip, use_container_width=True)

# --- Ranking storico comuni/contesti ---
st.subheader("Comuni/contesti più colpiti (nella finestra selezionata, tutti gli anni in archivio)")
col_a, col_b = st.columns(2)
dimensione = col_a.radio("Raggruppa per", ["Comune", "Contesto"], horizontal=True, key="dim_ranking_storico")
top_n = col_b.radio("Mostra", [10, 20], horizontal=True, format_func=lambda n: f"Top {n}", key="top_n_storico")
colonna = "comune" if dimensione == "Comune" else "contesto"

ranking = archivio_finestra[colonna].dropna().value_counts().head(top_n).reset_index()
ranking.columns = [dimensione.lower(), "eventi"]
fig_ranking = px.bar(
    ranking.sort_values("eventi"), x="eventi", y=dimensione.lower(), orientation="h",
    color_discrete_sequence=[CATEGORICO[0]],
)
fig_ranking.update_layout(xaxis_title="Eventi", yaxis_title="", showlegend=False, height=max(300, 24 * top_n))
st.plotly_chart(fig_ranking, use_container_width=True)

csv = archivio_finestra.to_csv(index=False).encode("utf-8-sig")
st.download_button(
    "⬇️ Esporta dati della finestra selezionata (CSV)", data=csv,
    file_name=f"storico_siger_{mm_dd_inizio.strftime('%m%d')}_{mm_dd_fine.strftime('%m%d')}.csv",
    mime="text/csv",
)
