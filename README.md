<div align="center">

# 🎙️ Fluency 01

### Real-Time AI English Tutor — Voice & Text

*Un tutor AI nativo sempre disponibile, a costo zero.*

[![Live Demo](https://img.shields.io/badge/Live_Demo-Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://fluency-ai.streamlit.app)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.32+-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Groq](https://img.shields.io/badge/Groq-Llama_3.1-F55036?style=flat-square)](https://groq.com)
[![Whisper](https://img.shields.io/badge/Whisper-faster--whisper-412991?style=flat-square)](https://github.com/SYSTRAN/faster-whisper)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)
[![Cost](https://img.shields.io/badge/Running_Cost-€0%2Fmese-22c55e?style=flat-square)](https://groq.com)

---

**Fluency 01** è un'applicazione web full-stack per la pratica dell'inglese con un tutor AI.  
Parli al microfono, ricevi una risposta vocale in meno di 1.5 secondi, e ottieni correzioni grammaticali in tempo reale — tutto gratuitamente, senza infrastruttura cloud.

🚀 **[Prova live → fluency-ai.streamlit.app](https://fluency-ai.streamlit.app)**

[Funzionalità](#-funzionalità) · [Demo Pipeline](#-come-funziona) · [Installazione](#-installazione) · [Architettura](#-architettura) · [Changelog](#-changelog)

</div>

---

## 🧠 Perché questo progetto

La maggior parte degli strumenti per l'apprendimento delle lingue è o troppo costosa, o troppo passiva. Fluency 01 nasce da una domanda semplice: **è possibile costruire un tutor vocale AI di qualità, completamente gratuito, con latenza inferiore a 2 secondi?**

La risposta è sì — combinando quattro tecnologie open/free-tier in una pipeline ottimizzata:

- **Whisper locale** elimina i costi di trascrizione
- **Groq Free Tier** offre inferenza LLM a velocità sorprendente (~300ms)
- **edge-tts** sfrutta le voci neurali Microsoft senza API key
- **Streamlit** permette un frontend ricco senza framework JS separati

Il risultato è un'app con latenza totale **< 1.5 secondi** e costo operativo di **€0,00/mese**.

---

## ✨ Funzionalità

### 🎙️ Push-to-Talk Hero
Un componente Streamlit custom scritto da zero in HTML/JS puro. Usa la **Web Audio API** per catturare audio a 16kHz, lo codifica come WAV (RIFF header + PCM 16-bit) interamente nel browser, e lo invia a Python via `postMessage`. Il bottone risponde allo **[Spazio]** su tastiera tramite listener cross-iframe su `window.top`.

- Hold to record, release to send — zero configurazione
- Feedback visivo animato: halo ring rotante in idle, pulse rosso in registrazione, waveform in tempo reale
- Scarta automaticamente clip < 300ms (anti-accidentale)

### 🗣️ Pipeline Voice-to-Voice
```
🎤  Audio WAV (base64)
     ↓
🔤  faster-whisper  ──────────────────────────  < 500ms
     beam_size=5 · vad_filter · initial_prompt
     ↓
🧠  Groq / Llama 3.1-8b-instant  ───────────  < 300ms
     JSON dual-track: {correction, reply}
     ↓
🔊  edge-tts Microsoft Neural  ──────────────  < 600ms
     5 voci · GB / AU / US accent sync
     ↓
📱  Streamlit UI  ───────────────────────────  istantaneo
     iMessage bubbles · badge correzione · XP bar
```

### 🌍 Regional Intelligence
Il system prompt dell'LLM si sincronizza automaticamente con la voce TTS selezionata. Nessuna libreria esterna — logica pura sulla stringa `voice_model`:

| Voce | Variante | Esempi |
|---|---|---|
| `en-GB-*` | British English | `flat`, `lift`, `cheers`, spelling `-ise/-our` |
| `en-AU-*` | Australian English | `mate`, `arvo`, `no worries`, `reckon` |
| `en-US-*` | American English | default, vocabolario standard |

### ✍️ Modalità Focus (Text & Drills)
Una seconda modalità completamente diversa dalla conversazione vocale. Senza STT né TTS, il prompt di sistema diventa quello di un **professore di grammatica universitario**: fornisce analisi approfondita degli errori, 2-3 alternative native, e propone micro-esercizi (fill-in-the-gap, translation drill, error spotting) dopo ogni messaggio.

```json
{
  "correction": "Spiegazione dettagliata della regola grammaticale in italiano...",
  "alternatives": "Un madrelingua direbbe: (1) '...' (2) '...' (3) '...'",
  "reply": "Risposta + micro-esercizio per consolidare la regola"
}
```

### 🛡️ Resilienza API
Integrazione `tenacity` con eccezione custom `GroqRateLimitError`. Su errore 429, retry automatico con **backoff esponenziale** (2→10s, max 3 tentativi). L'interfaccia non crasha mai — in caso di fallimento definitivo compare un `st.toast` in italiano.

### 📥 Esporta & Studia
- **Anki CSV** — ogni errore della sessione diventa una flashcard (`fluency_flashcards.csv`, delimitatore `;`, BOM UTF-8)
- **Session Report** — Markdown scaricabile con statistiche, tabella errori numerata e link alle flashcard. Compatibile con Obsidian, Notion, VS Code

### 📊 Gamification XP
Barra progress orizzontale con fill dinamico che cambia colore in base all'accuracy (🟢 verde ≥80% · 🟡 amber ≥50% · 🔴 rosso <50%), con transizione `cubic-bezier` springy ad ogni scambio.

### 📱 Progressive Web App
`manifest.json` iniettato via data URI (cross-version Streamlit), meta tag per iOS/Android, installabile come app nativa su mobile e desktop.

---

## 🏗️ Architettura

```
fluency-ai/
│
├── app.py                          # Entry point — orchestrazione UI e pipeline
│
├── logic/
│   ├── llm_handler.py              # Groq API · dual/triple-track JSON · retry
│   ├── stt_engine.py               # faster-whisper · VAD · context prompt
│   └── tts_engine.py               # edge-tts · async in thread isolato
│
├── components/
│   ├── push_to_talk.py             # Wrapper Python (declare_component)
│   └── ptt_frontend/
│       └── index.html              # Web Audio API · WAV encoder · spacebar bridge
│
├── utils/
│   ├── helpers.py                  # CSV Anki · Markdown report · audio utils
│   └── styles.css                  # Design System v4 · Nunito · iMessage bubbles
│
├── static/
│   └── manifest.json               # PWA manifest
│
└── .streamlit/
    └── config.toml                 # Tema locked · brand colors
```

**Decisioni architetturali rilevanti:**

- Il componente PTT è un `declare_component` Streamlit che comunica via `postMessage` — evita qualsiasi dipendenza da librerie audio Python non stabili
- Il TTS gira sempre in un thread separato con `asyncio.new_event_loop()` per evitare conflitti con l'event loop di Streamlit
- Il parsing JSON dell'LLM implementa 4 livelli di fallback progressivi (parse diretto → estrai `{}` → clean newlines → regex extraction) per gestire output malformati
- Il manifest PWA viene iniettato come **Blob data URI** per essere indipendente dal path di static file serving di Streamlit (che cambia tra versioni)

---

## ⚡ Stack Tecnologico

| Layer | Tecnologia | Motivazione |
|---|---|---|
| **Frontend** | Streamlit + CSS custom | Rapid prototyping, nessun JS framework |
| **Audio capture** | Web Audio API (JS custom component) | Controllo totale su sample rate e encoding |
| **STT** | `faster-whisper` (locale) | Zero costi, privacy, ~200ms su CPU |
| **LLM** | Groq API · `llama-3.1-8b-instant` | ~300ms inference, free tier generoso |
| **TTS** | `edge-tts` · Microsoft Neural | Zero costi, 5 voci neurali, accenti multipli |
| **Retry** | `tenacity` | Backoff esponenziale dichiarativo |
| **Font** | Nunito (Google Fonts) | Leggibilità e carattere "friendly" |

---

## 🚀 Installazione

**Prerequisiti:** Python 3.10+, Git

```bash
# 1. Clona il repository
git clone https://github.com/tuo-username/fluency-ai.git
cd fluency-ai

# 2. Crea un virtual environment (consigliato)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3. Installa le dipendenze
pip install -r requirements.txt

# 4. Configura le variabili d'ambiente
cp .env.example .env
# Apri .env e inserisci la tua chiave Groq

# 5. Avvia
streamlit run app.py
```

La chiave Groq è gratuita su [console.groq.com](https://console.groq.com) — nessuna carta di credito richiesta.

---

## ⚙️ Configurazione

```env
# .env

GROQ_API_KEY=gsk_...          # Obbligatorio — gratuito su console.groq.com
WHISPER_MODEL=base             # base | small | medium  (velocità vs accuratezza)
VOICE_MODEL=en-US-GuyNeural   # Voce TTS — determina anche il registro linguistico
MAX_TOKENS=512                 # Lunghezza massima risposta LLM
TEMPERATURE=0.7                # Creatività LLM (0.0 = deterministico, 1.0 = creativo)
```

---

## 🎭 Scenari e Difficoltà

**5 scenari** con personaggi AI distinti e opening message hardcoded (zero latenza):

| Scenario | Personaggio AI | Focus |
|---|---|---|
| 💬 Free Talk | Amico nativo curioso | Conversazione aperta |
| 💼 Job Interview | HR Recruiter (Sarah) | Lessico professionale |
| ✈️ Travel | Check-in agent · Hotel receptionist | Situazioni pratiche |
| 🍽️ Restaurant | Cameriere (James) | Ordini e richieste |
| ☀️ Small Talk | Collega informale | Espressioni idiomatiche |

**3 livelli di difficoltà** che controllano sia la complessità delle risposte che la profondità delle correzioni:

| Livello | Risposte | Correzioni |
|---|---|---|
| 🟢 Beginner | Frasi brevi, vocabolario semplice | Solo errori gravi, in italiano semplice |
| 🟡 Intermediate | Frasi naturali, idiomi graduali | Errori grammaticali con regola spiegata |
| 🔴 Advanced | Ricco, strutture complesse, phrasal verbs | Anche phrasing non idiomatico, alternative native |

---

## 📋 Changelog

### v4.0 — UI Revolution
- 🎨 **Redesign totale** "Bouncy & Alive" — font Nunito, sfondo `#f0f4f8`, sidebar dark slate
- 💬 **iMessage bubbles** — gradiente blu user, shadow AI, border-radius 20px con coda asimmetrica
- ⚠️ **Correction badge** — `<details><summary>` HTML nativo, badge rosso cliccabile
- ⚡ **XP bar** — barra progress gamificata con colore dinamico e animazione spring
- 🎙️ **PTT Hero** — bottone 96px con halo ring rotante, pulse animato, inset highlight
- 📱 **PWA** — `manifest.json` via Blob data URI, meta tag iOS/Android, installabile

### v3.0 — Intelligence & Export
- 🌍 **Regional Intelligence** — vocabolario LLM sincronizzato con accento TTS (GB/AU/US)
- 🛡️ **Retry anti-crash** — `tenacity` + `GroqRateLimitError` + backoff esponenziale
- 📥 **Anki Export** — `generate_anki_csv()` → CSV con BOM UTF-8 pronto per import
- 📄 **Session Report** — `generate_session_report()` → Markdown con tabella errori

### v2.0 — Voice & Scenarios
- 🎙️ **PTT custom** — sostituisce `audio-recorder-streamlit` con Web Audio API
- ⌨️ **Spacebar shortcut** — listener cross-iframe su `window.top`
- 🎭 **5 scenari** con opener automatici hardcoded (zero latenza)
- 📊 **Difficoltà** Beginner / Intermediate / Advanced
- 🔧 **STT** — `beam_size` 1→5, `initial_prompt` contestuale
- 🧠 **LLM** — modello aggiornato a `llama-3.1-8b-instant`, parsing JSON a 4 livelli

### v1.0 — Foundation
- Pipeline base Voice → Whisper → Groq → edge-tts → Streamlit
- Dual-Track Feedback (correzione + risposta simultanea)
- Autoplay vocale, memoria conversazione, cleanup file temporanei

---

<div align="center">

**Costruito interamente con stack open/free-tier · Costo operativo: €0,00/mese**

*Fluency 01 è un progetto portfolio — ogni decisione tecnica è documentata e motivata.*

</div>
