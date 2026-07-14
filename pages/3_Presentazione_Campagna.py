"""Pagina pubblica di sintesi campagna, pensata per essere condivisa (es. prima della
cabina di regia del martedì): nessuna credenziale SIGER richiesta, legge solo l'archivio
storico persistente e si aggiorna da sola ad ogni visita. Stessa logica di calcolo della
sezione "Confronto con il 2025" della Dashboard (vedi siger_confronto.py), presentata in
un formato più simile a un report da mostrare che a una dashboard di lavoro.
"""
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

import siger_confronto
import siger_storico

CATEGORICO = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]

st.set_page_config(page_title="Stato Campagna AIB - SIGER", layout="wide", page_icon="🔥")

st.markdown(
    """
    <style>
    .siger-hero {
        background: linear-gradient(135deg, #1a4d8f 0%, #2a78d6 60%, #4a9de0 100%);
        color: white; padding: 2.2rem 2.5rem; border-radius: 14px; margin-bottom: 1.5rem;
    }
    .siger-hero h1 { margin: 0; font-size: 2.1rem; }
    .siger-hero p { margin: 0.4rem 0 0 0; font-size: 1.05rem; opacity: 0.92; }
    div[data-testid="stMetric"] {
        background-color: rgba(127, 127, 127, 0.06); border-radius: 10px;
        padding: 0.9rem 1rem; border: 1px solid rgba(127, 127, 127, 0.15);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

oggi = date.today()
generato_il = datetime.now().strftime("%d/%m/%Y alle %H:%M")

st.markdown(
    f"""
    <div class="siger-hero">
        <h1>🔥 Stato della campagna Antincendio Boschivo {oggi.year}</h1>
        <p>Regione Basilicata · Protezione Civile — aggiornato automaticamente ad ogni apertura di questa pagina</p>
    </div>
    """,
    unsafe_allow_html=True,
)

archivio = siger_storico.carica_archivio(dict(st.secrets))
cf = siger_confronto.calcola_confronto(archivio, oggi)

if cf is None:
    st.info(
        "Dati insufficienti per il confronto con l'anno precedente: serve almeno un evento "
        "nell'archivio storico nella stessa finestra 1/07 → oggi dell'anno scorso."
    )
    st.stop()

etichetta_finestra = f"1/07 → {oggi.strftime('%d/%m/%Y')}"
variazione = cf["variazione"]

if variazione is None:
    st.info(f"Zero eventi nel {cf['anno_precedente']} in questa finestra: variazione non calcolabile.")
elif variazione > 0:
    st.warning(
        f"### 🔺 La campagna {cf['anno_corrente']} è al **{variazione:+.1f}%** rispetto allo stesso "
        f"periodo del {cf['anno_precedente']}\n"
        f"**{cf['tot_corr']}** eventi quest'anno contro **{cf['tot_prec']}** nello stesso periodo del "
        f"{cf['anno_precedente']} ({etichetta_finestra})."
    )
else:
    st.success(
        f"### 🔻 La campagna {cf['anno_corrente']} è al **{variazione:+.1f}%** rispetto allo stesso "
        f"periodo del {cf['anno_precedente']}\n"
        f"**{cf['tot_corr']}** eventi quest'anno contro **{cf['tot_prec']}** nello stesso periodo del "
        f"{cf['anno_precedente']} ({etichetta_finestra})."
    )

col1, col2, col3, col4 = st.columns(4)
col1.metric(f"Eventi {cf['anno_corrente']} ({etichetta_finestra})", cf["tot_corr"])
col2.metric(f"Eventi {cf['anno_precedente']} (stessa finestra)", cf["tot_prec"])
col3.metric(
    "Variazione anno su anno", f"{variazione:+.1f}%" if variazione is not None else "n/d",
    delta=f"{variazione:+.1f}%" if variazione is not None else None, delta_color="inverse",
)
giorni_boschivi_corr = int((cf["arch_corr"]["tipologia"] == "Incendio Boschivo").sum())
col4.metric("Incendi boschivi quest'anno", giorni_boschivi_corr)

st.divider()

# --- Andamento cumulato ---
st.markdown("### 📈 Andamento della campagna")
fig_cum = px.line(
    cf["df_cum"], x="giorno_campagna", y="eventi_cumulati", color="anno",
    color_discrete_map={str(cf["anno_corrente"]): CATEGORICO[0], str(cf["anno_precedente"]): CATEGORICO[5]},
)
fig_cum.update_layout(
    xaxis_title="Giorni dall'inizio campagna (1/07)", yaxis_title="Eventi cumulati", legend_title="",
    height=420,
)
fig_cum.update_traces(line=dict(width=3))
st.plotly_chart(fig_cum, use_container_width=True)

st.divider()

# --- Tipologia e territorio ---
st.markdown("### 🗂️ Tipologia e territorio")
col_a, col_b = st.columns(2)
with col_a:
    st.write("**Per tipologia**")
    df_tip, ordine_tip = siger_confronto.confronto_categoria(
        cf["arch_prec"], cf["arch_corr"], "tipologia", cf["anno_precedente"], cf["anno_corrente"],
        ordine_fisso=siger_confronto.ORDINE_TIPOLOGIA,
    )
    fig_tip = px.bar(
        df_tip, x="categoria", y="eventi", color="anno", barmode="group",
        category_orders={"categoria": ordine_tip},
        color_discrete_map={str(cf["anno_corrente"]): CATEGORICO[0], str(cf["anno_precedente"]): CATEGORICO[5]},
    )
    fig_tip.update_layout(xaxis_title="", yaxis_title="Eventi", legend_title="", height=380)
    st.plotly_chart(fig_tip, use_container_width=True)

with col_b:
    st.write("**Comuni più colpiti (Top 12)**")
    df_terr, ordine_terr = siger_confronto.confronto_categoria(
        cf["arch_prec"], cf["arch_corr"], "comune", cf["anno_precedente"], cf["anno_corrente"], top_n=12,
    )
    fig_terr = px.bar(
        df_terr, x="eventi", y="categoria", color="anno", orientation="h", barmode="group",
        category_orders={"categoria": ordine_terr},
        color_discrete_map={str(cf["anno_corrente"]): CATEGORICO[0], str(cf["anno_precedente"]): CATEGORICO[5]},
    )
    fig_terr.update_layout(xaxis_title="Eventi", yaxis_title="", legend_title="", height=380)
    st.plotly_chart(fig_terr, use_container_width=True)

st.divider()

# --- Giorno della settimana e fascia oraria ---
st.markdown("### 🕒 Quando succede")
col_c, col_d = st.columns(2)
with col_c:
    st.write("**Per giorno della settimana**")
    df_giorno, ordine_giorno = siger_confronto.confronto_categoria(
        cf["arch_prec_orari"], cf["arch_corr_orari"], "giorno_settimana",
        cf["anno_precedente"], cf["anno_corrente"], ordine_fisso=siger_confronto.ORDINE_GIORNI,
    )
    fig_giorno = px.bar(
        df_giorno, x="categoria", y="eventi", color="anno", barmode="group",
        category_orders={"categoria": ordine_giorno},
        color_discrete_map={str(cf["anno_corrente"]): CATEGORICO[0], str(cf["anno_precedente"]): CATEGORICO[5]},
    )
    fig_giorno.update_layout(xaxis_title="", yaxis_title="Eventi", legend_title="", height=380)
    st.plotly_chart(fig_giorno, use_container_width=True)

with col_d:
    st.write("**Per fascia oraria**")
    df_fascia, ordine_fascia = siger_confronto.confronto_categoria(
        cf["arch_prec_orari"], cf["arch_corr_orari"], "fascia",
        cf["anno_precedente"], cf["anno_corrente"], ordine_fisso=siger_confronto.ORDINE_FASCIA,
    )
    fig_fascia = px.bar(
        df_fascia, x="categoria", y="eventi", color="anno", barmode="group",
        category_orders={"categoria": ordine_fascia},
        color_discrete_map={str(cf["anno_corrente"]): CATEGORICO[0], str(cf["anno_precedente"]): CATEGORICO[5]},
    )
    fig_fascia.update_layout(xaxis_title="", yaxis_title="Eventi", legend_title="", height=380)
    st.plotly_chart(fig_fascia, use_container_width=True)

st.caption(
    "Giorno/ora ricavati dalla data di apertura in archivio: per gli eventi importati da Excel "
    "senza orario esplicito l'ora può risultare 00:00 e sottostimare le fasce diurne — da leggere "
    "con cautela per gli anni più vecchi."
)

st.divider()
st.caption(f"Report generato automaticamente il {generato_il} · Fonte: archivio storico SIGER, {len(archivio)} eventi totali dal {archivio['data_inizio'].min().strftime('%d/%m/%Y') if not archivio.empty else 'n/d'}.")
