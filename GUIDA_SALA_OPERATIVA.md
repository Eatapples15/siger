# Guida per la sala operativa — Report SIGER

Guida rapida per chi usa il tool in sala operativa: come generare il report del giorno e
come usare il bot Telegram. Non serve nessuna competenza tecnica.

## 1. Il report di oggi — due modi per averlo

### A) Dal sito web

1. Apri il link dell'app (quello che ti ha dato chi gestisce il tool).
2. Nella pagina principale, premi **"🚀 Genera report di oggi"**.
3. Aspetta 30-60 secondi (il tool si collega al portale SIGER, scarica i dati e li
   elabora) — vedrai una barra con i passaggi in corso.
4. Il PDF si scarica automaticamente sul tuo computer appena pronto.
5. Se hai spuntato **"Invia il report su Telegram al termine"** prima di premere il
   bottone, il PDF arriva anche sulla chat Telegram configurata, senza altri passaggi.

Il report contiene: elenco degli incendi gestiti oggi (tipologia, livello di rischio,
mezzi impiegati), e una sezione a parte per gli incendi aperti nei giorni precedenti e
ancora in corso.

C'è anche **"📅 Genera report settimanale"** accanto, stesso funzionamento, per la
settimana in corso (utile per la cabina di regia del martedì) — include il confronto con
la settimana precedente quando disponibile.

### B) Dal bot Telegram (comodo da telefono, non serve aprire il sito)

Vedi sezione 2 qui sotto.

## 2. Il bot Telegram

### Come iniziare

1. Cerca il bot su Telegram (chi gestisce il tool ti darà il nome) e apri la chat.
2. Scrivi **/start** (o semplicemente apri la chat se l'hai già usato prima).
3. Il bot risponde con un messaggio di benvenuto e **due pulsanti** sotto il messaggio:
   - **📄 Report di oggi**
   - **❓ Guida**

Da qui in poi non serve scrivere comandi: **tocca il pulsante** che ti serve.

### Chiedere il report

Tocca **📄 Report di oggi** (oppure scrivi `/report`). Il bot risponde subito con un
messaggio di conferma ("generazione in corso..."), poi — dopo 30-60 secondi — invia
direttamente il PDF nella chat, pronto da inoltrare o salvare.

Non serve fare nient'altro nel frattempo: puoi anche chiudere Telegram e riaprirlo dopo,
il PDF resterà nella chat quando arriva.

### Se il bot dice che non sei autorizzato

Solo le chat autorizzate possono chiedere report. Se provi e il bot ti risponde che non
sei autorizzato, ti mostra il tuo **chat id**: comunicalo a chi gestisce il tool, che ti
aggiungerà all'elenco (`TELEGRAM_CHAT_IDS` nella configurazione). Da quel momento in poi
puoi chiedere report normalmente.

### Rivedere la guida in qualsiasi momento

Tocca **❓ Guida** (o scrivi `/help`) e il bot rimanda lo stesso messaggio con i pulsanti.

## 3. Altri strumenti disponibili (sul sito web)

Oltre al report del giorno, l'app ha altre pagine nel menu laterale:

- **📊 Dashboard Statistiche** — grafici sull'andamento della campagna nel periodo che
  scegli tu (oggi, ultima settimana, ultimo mese, o un intervallo a tua scelta), inclusa
  una sezione che confronta l'andamento di quest'anno con lo stesso periodo del 2025.
- **📈 Confronto Storico** — confronto anno su anno su tutto l'archivio storico
  (2019-oggi), per tipologia e per comune/contesto.
- **🔥 Presentazione Campagna** — una sintesi visiva pronta da mostrare (es. in cabina di
  regia), sempre aggiornata da sola: numero di incendi quest'anno vs 2025, andamento,
  tipologie, territorio, giorni/orari — non serve premere nessun bottone, si aggiorna ad
  ogni apertura della pagina.

## Domande frequenti

**Il report impiega più di un minuto, è normale?**
Sì, può capitare se il portale SIGER è lento o se il periodo richiesto ha molti eventi.
Se dopo 3-4 minuti non hai ancora ricevuto nulla, riprova o segnalalo a chi gestisce il
tool.

**Le coordinate sulla mappa non sono precise per tutti gli eventi, perché?**
Il tool legge le coordinate dal diario evento quando un operatore le scrive nel testo
libero. Se non sono scritte lì, l'evento viene comunque mostrato sulla mappa ma posizionato
in modo approssimato sul comune (non sul punto esatto). È indicato in mappa quali sono
precise e quali approssimate.

**Posso usare il bot da più persone/telefoni contemporaneamente?**
Sì, ogni chat autorizzata può chiedere il report in modo indipendente.
