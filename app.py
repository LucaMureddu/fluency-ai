"""
app.py — Fluency 01 · Real-Time AI English Tutor
Design: Minimal Pro v3
"""

import os, base64, time
import streamlit as st
from dotenv import load_dotenv

from components.push_to_talk import push_to_talk_button
from logic.stt_engine      import transcribe_audio, load_whisper_model
from logic.llm_handler     import call_llm, TOPIC_CONTEXTS, TOPIC_OPENERS, GroqRateLimitError
from logic.tts_engine      import synthesize_speech
from utils.helpers import (
    save_audio_bytes, delete_file, cleanup_temp_files,
    audio_file_to_base64, format_correction_message,
    generate_anki_csv, generate_session_report,
)

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Fluency 01",
    page_icon="🎙️",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
css_path = os.path.join(os.path.dirname(__file__), "utils", "styles.css")
with open(css_path) as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# ── PWA support ───────────────────────────────────────────────────────────────
# Il manifest viene iniettato come data URI per non dipendere dal path di serving
# di Streamlit (che varia tra versioni). Funziona su localhost e in produzione.
import json as _json, pathlib as _pl
_manifest_path = _pl.Path(__file__).parent / "static" / "manifest.json"
_manifest_json = _manifest_path.read_text(encoding="utf-8") if _manifest_path.exists() else "{}"
_manifest_escaped = _manifest_json.replace("`", r"\`").replace("\\", "\\\\")

st.markdown(f"""
<script>
(function() {{
  // Evita di re-iniettare ad ogni rerun di Streamlit
  if (document.querySelector('link[rel="manifest"]')) return;

  // Manifest via data URI — funziona anche senza static file serving
  const manifestStr = `{_manifest_escaped}`;
  const blob = new Blob([manifestStr], {{ type: 'application/manifest+json' }});
  const url  = URL.createObjectURL(blob);

  const link = document.createElement('link');
  link.rel   = 'manifest';
  link.href  = url;
  document.head.appendChild(link);

  // Meta tags PWA & mobile
  const metas = [
    ['mobile-web-app-capable',            'yes'],
    ['apple-mobile-web-app-capable',      'yes'],
    ['apple-mobile-web-app-status-bar-style', 'black-translucent'],
    ['apple-mobile-web-app-title',        'Fluency 01'],
    ['application-name',                  'Fluency 01'],
    ['theme-color',                       '#6366f1'],
    ['msapplication-TileColor',           '#6366f1'],
    ['msapplication-navbutton-color',     '#6366f1'],
    ['format-detection',                  'telephone=no'],
  ];
  metas.forEach(([name, content]) => {{
    if (document.querySelector(`meta[name="${{name}}"]`)) return;
    const m = document.createElement('meta');
    m.name    = name;
    m.content = content;
    document.head.appendChild(m);
  }});

  // Aggiorna il title per coerenza
  document.title = 'Fluency 01 — AI English Tutor';
}})();
</script>
""", unsafe_allow_html=True)

# Top accent bar
st.markdown('<div class="fl-top-bar"></div>', unsafe_allow_html=True)

# ── Session defaults ──────────────────────────────────────────────────────────
MODE_VOICE = "🎙️ Fluency (Voice)"
MODE_TEXT  = "✍️ Focus (Text & Drills)"

DEFAULTS = dict(
    messages=[], last_audio_file=None, session_started=False,
    total_exchanges=0, corrections=0, last_audio_hash=None,
    difficulty="Intermediate", topic=None, opener_played=False,
    study_mode=MODE_VOICE,
)
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

if not st.session_state.session_started:
    cleanup_temp_files()
    st.session_state.session_started = True

with st.spinner(""):
    load_whisper_model()

# ── Metadata ──────────────────────────────────────────────────────────────────
TOPICS = {
    "Free Talk":     {"icon": "💬", "desc": "Conversazione libera su qualsiasi argomento"},
    "Job Interview": {"icon": "💼", "desc": "Pratica colloqui di lavoro in inglese"},
    "Travel":        {"icon": "✈️", "desc": "Aeroporti, hotel, indicazioni stradali"},
    "Restaurant":    {"icon": "🍽️", "desc": "Ordina, chiedi, interagisci al ristorante"},
    "Small Talk":    {"icon": "☀️", "desc": "Chiacchiere quotidiane da madrelingua"},
}
DIFFICULTIES = {
    "Beginner":     "🟢",
    "Intermediate": "🟡",
    "Advanced":     "🔴",
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def autoplay(mp3_path: str):
    b64 = audio_file_to_base64(mp3_path)
    st.html(f"""<audio autoplay style="display:none">
      <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
    </audio>
    <script>
      document.querySelectorAll('audio[autoplay]').forEach(a=>a.play().catch(()=>{{}}));
    </script>""")


def render_message(role, content, correction=None, alternatives=None):
    import re as _re
    avatar = "🧑" if role == "user" else "🤖"
    st.markdown(f"""
    <div class="fl-msg {role}">
      <div class="fl-avatar">{avatar}</div>
      <div class="fl-bubble">{content}</div>
    </div>""", unsafe_allow_html=True)

    if role != "user":
        return

    # ── Correzione: badge cliccabile <details> (entrambe le modalità) ──────────
    if correction:
        clean = correction.lstrip("💡 ").strip()
        st.markdown(f"""
        <details class="fl-correction-badge">
          <summary>⚠️ Correzione grammaticale</summary>
          <div class="fl-correction-body">{clean}</div>
        </details>""", unsafe_allow_html=True)

    # ── Modalità Focus: expander con analisi profonda e alternative ────────────
    if alternatives:
        with st.expander("💡 Espandi per analisi dettagliata e alternative"):
            if correction:
                clean = correction.lstrip("💡 ").strip()
                st.markdown("#### ✏️ Analisi grammaticale")
                # Spezza su ". Corretto:" per mettere la versione corretta in evidenza
                lines = [l.strip() for l in clean.replace(". Corretto:", "\n**Corretto:**").split(". ") if l.strip()]
                for line in lines:
                    if line:
                        st.markdown(f"- {line}{'.' if not line.endswith('.') else ''}")
                st.markdown("")

            st.markdown("#### 🗣️ Come lo direbbe un madrelingua")
            # Spezza sulle numerazioni (1) (2) (3) prodotte dal LLM Focus
            parts   = _re.split(r'\s*\(\d+\)\s*', alternatives)
            intro   = parts[0].strip() if parts else ""
            phrases = [p.strip().strip('"').strip("'") for p in parts[1:] if p.strip()]
            if intro:
                st.markdown(f"*{intro}*")
            if phrases:
                for phrase in phrases:
                    st.markdown(f'- **"{phrase}"**')
            else:
                st.markdown(alternatives)


def play_opener(topic: str):
    """
    Invia il primo messaggio del tutor in personaggio appena si seleziona il topic.
    Genera l'audio e lo aggiunge alla chat — latenza zero perché è hardcoded.
    """
    opener = TOPIC_OPENERS.get(topic, TOPIC_OPENERS["Free Talk"])
    try:
        mp3_path = synthesize_speech(opener)
        if st.session_state.last_audio_file:
            delete_file(st.session_state.last_audio_file)
        st.session_state.last_audio_file = mp3_path
        st.session_state.messages.append({"role": "assistant", "content": opener})
        st.session_state.opener_played = True
    except Exception as e:
        # Se TTS fallisce, mostra comunque il messaggio scritto
        st.session_state.messages.append({"role": "assistant", "content": opener})
        st.session_state.opener_played = True
        print(f"[Opener TTS error] {e}")


def run_pipeline(audio_b64: str):
    wav_path = mp3_path = None
    t_start = time.time()
    try:
        wav_path = save_audio_bytes(base64.b64decode(audio_b64), suffix=".wav")

        with st.spinner("Trascrizione…"):
            t0 = time.time()
            transcript = transcribe_audio(wav_path)
            stt_ms = (time.time() - t0) * 1000

        if not transcript:
            st.toast("Non ho sentito nulla — riprova.", icon="🎙️")
            return

        with st.spinner("Il tutor risponde…"):
            t1 = time.time()
            result = call_llm(
                st.session_state.messages, transcript,
                difficulty=st.session_state.difficulty,
                topic=st.session_state.topic or "Free Talk",
                voice_model=os.environ.get("VOICE_MODEL", "en-US-GuyNeural"),
                study_mode=st.session_state.study_mode,
            )
            llm_ms = (time.time() - t1) * 1000

        with st.spinner("Sintesi vocale…"):
            t2 = time.time()
            mp3_path = synthesize_speech(result["reply"])
            tts_ms = (time.time() - t2) * 1000

        if st.session_state.last_audio_file:
            delete_file(st.session_state.last_audio_file)
        st.session_state.last_audio_file = mp3_path

        correction_fmt = format_correction_message(result.get("correction"))
        st.session_state.messages += [
            {"role": "user",      "content": transcript,      "correction": correction_fmt},
            {"role": "assistant", "content": result["reply"]},
        ]
        st.session_state.total_exchanges += 1
        if result.get("correction"):
            st.session_state.corrections += 1

        total_ms = (time.time() - t_start) * 1000
        print(f"[Pipeline] {stt_ms:.0f}ms STT · {llm_ms:.0f}ms LLM · {tts_ms:.0f}ms TTS · {total_ms:.0f}ms TOT")
        st.rerun()

    except GroqRateLimitError:
        st.toast(
            "I server sono momentaneamente saturi. Riprova tra pochi secondi.",
            icon="⏳",
        )
    except ValueError as e:
        st.error(f"❌ Configurazione: {e}")
    except RuntimeError as e:
        st.error(f"❌ API: {e}")
    except Exception as e:
        st.error(f"❌ {e}")
    finally:
        delete_file(wav_path)


def run_text_pipeline(text_input: str):
    """
    Pipeline testuale per la Modalità Focus.
    Salta STT (Whisper) e TTS (edge-tts): chiama direttamente l'LLM
    e aggiorna i messaggi a schermo. Latenza target: < 350ms.
    """
    text_input = text_input.strip()
    if not text_input:
        return

    t_start = time.time()
    try:
        with st.spinner("Il tutor risponde…"):
            t1 = time.time()
            result = call_llm(
                st.session_state.messages, text_input,
                difficulty=st.session_state.difficulty,
                topic=st.session_state.topic or "Free Talk",
                voice_model=os.environ.get("VOICE_MODEL", "en-US-GuyNeural"),
                study_mode=st.session_state.study_mode,
            )
            llm_ms = (time.time() - t1) * 1000

        correction_fmt = format_correction_message(result.get("correction"))
        st.session_state.messages += [
            {"role": "user",      "content": text_input,     "correction": correction_fmt,
             "alternatives": result.get("alternatives")},
            {"role": "assistant", "content": result["reply"]},
        ]
        st.session_state.total_exchanges += 1
        if result.get("correction"):
            st.session_state.corrections += 1

        total_ms = (time.time() - t_start) * 1000
        print(f"[Text Pipeline] {llm_ms:.0f}ms LLM · {total_ms:.0f}ms TOT")
        st.rerun()

    except GroqRateLimitError:
        st.toast(
            "I server sono momentaneamente saturi. Riprova tra pochi secondi.",
            icon="⏳",
        )
    except ValueError as e:
        st.error(f"❌ Configurazione: {e}")
    except RuntimeError as e:
        st.error(f"❌ API: {e}")
    except Exception as e:
        st.error(f"❌ {e}")


# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Fluency 01** &nbsp;·&nbsp; Settings", unsafe_allow_html=True)
    st.markdown("---")

    # Difficulty
    st.markdown('<span class="fl-label">Difficoltà</span>', unsafe_allow_html=True)
    diff_cols = st.columns(3)
    for i, (lvl, dot) in enumerate(DIFFICULTIES.items()):
        with diff_cols[i]:
            active = st.session_state.difficulty == lvl
            if st.button(
                f"{dot} {lvl[:3] if lvl == 'Intermediate' else lvl}",
                key=f"diff_{lvl}",
                type="primary" if active else "secondary",
                use_container_width=True,
            ):
                if not active:
                    st.session_state.difficulty = lvl
                    st.rerun()

    st.markdown("---")

    # Topic
    st.markdown('<span class="fl-label">Scenario</span>', unsafe_allow_html=True)
    topic_list = list(TOPICS.keys())
    cur = topic_list.index(st.session_state.topic) if st.session_state.topic else 0
    sel = st.selectbox(
        "scenario", topic_list,
        index=cur,
        format_func=lambda t: f"{TOPICS[t]['icon']}  {t}",
        label_visibility="collapsed",
    )
    if sel != st.session_state.topic and st.session_state.topic is not None:
        st.session_state.topic = sel

    st.markdown("---")

    # Study mode
    st.markdown('<span class="fl-label">Modalità Studio</span>', unsafe_allow_html=True)
    study_mode = st.radio(
        "study_mode",
        [MODE_VOICE, MODE_TEXT],
        index=0 if st.session_state.study_mode == MODE_VOICE else 1,
        horizontal=True,
        label_visibility="collapsed",
    )
    if study_mode != st.session_state.study_mode:
        st.session_state.study_mode = study_mode
        st.rerun()

    st.markdown("---")

    # Voice
    st.markdown('<span class="fl-label">Voce</span>', unsafe_allow_html=True)
    voices = ["en-US-GuyNeural","en-US-JennyNeural","en-US-AriaNeural","en-GB-RyanNeural","en-AU-NatashaNeural"]
    voice = st.selectbox("voice", voices, label_visibility="collapsed")
    os.environ["VOICE_MODEL"] = voice

    st.markdown("---")

    # Stats
    st.markdown('<span class="fl-label">Sessione</span>', unsafe_allow_html=True)
    acc = round((1 - st.session_state.corrections / st.session_state.total_exchanges) * 100) \
          if st.session_state.total_exchanges else 100
    st.markdown(f"""
    <div class="fl-stats">
      <div class="fl-stat-row">
        <span class="fl-stat-label">Scambi</span>
        <span class="fl-stat-val">{st.session_state.total_exchanges}</span>
      </div>
      <div class="fl-stat-row">
        <span class="fl-stat-label">Correzioni</span>
        <span class="fl-stat-val">{st.session_state.corrections}</span>
      </div>
      <div class="fl-stat-row">
        <span class="fl-stat-label">Accuracy</span>
        <span class="fl-stat-val accent">{acc}%</span>
      </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # Stack
    st.markdown(f"""
    <div class="fl-stack">
      <div class="fl-stack-item"><span class="fl-stack-key">LLM</span> Llama 3.1 · Groq</div>
      <div class="fl-stack-item"><span class="fl-stack-key">STT</span> Whisper {os.getenv("WHISPER_MODEL","base")}</div>
      <div class="fl-stack-item"><span class="fl-stack-key">TTS</span> edge-tts · {voice.split('-')[2].replace('Neural','')}</div>
    </div>""", unsafe_allow_html=True)

    # Anki export
    st.markdown("---")
    st.markdown('<span class="fl-label">Flashcard</span>', unsafe_allow_html=True)
    has_corrections = st.session_state.corrections > 0
    anki_csv = generate_anki_csv(st.session_state.messages) if has_corrections else ""
    st.download_button(
        label="📥 Esporta Flashcard (Anki)",
        data=anki_csv,
        file_name="fluency_flashcards.csv",
        mime="text/csv",
        disabled=not has_corrections,
        use_container_width=True,
        help="Scarica le correzioni come flashcard CSV importabile in Anki"
              if has_corrections else
              "Nessuna correzione ancora — continua a parlare!",
    )

    # Session report
    has_session = st.session_state.total_exchanges > 0
    report_md   = generate_session_report(st.session_state) if has_session else ""
    st.download_button(
        label="📄 Scarica Report Lezione",
        data=report_md,
        file_name="fluency_report.md",
        mime="text/markdown",
        disabled=not has_session,
        use_container_width=True,
        help="Scarica il riepilogo della sessione in formato Markdown"
              if has_session else
              "Completa almeno uno scambio per generare il report",
    )

    st.markdown("")
    if st.button("↺  Nuova sessione", use_container_width=True):
        if st.session_state.last_audio_file:
            delete_file(st.session_state.last_audio_file)
        cleanup_temp_files()
        for k, v in DEFAULTS.items():
            st.session_state[k] = v
        st.session_state.session_started = True
        st.rerun()


# ── MAIN ──────────────────────────────────────────────────────────────────────
active_topic = st.session_state.topic or "Free Talk"
diff = st.session_state.difficulty

# Header
st.markdown(f"""
<div class="fl-header">
  <div class="fl-header-top">
    <div class="fl-logo">
      <div class="fl-logo-icon">🎙️</div>
      <span class="fl-logo-name">Fluency 01</span>
    </div>
    <div class="fl-badges">
      <span class="fl-badge accent">{TOPICS[active_topic]['icon']} {active_topic}</span>
      <span class="fl-badge">{DIFFICULTIES[diff]} {diff}</span>
    </div>
  </div>
  <div class="fl-header-sub">Real-time AI English Tutor · powered by Groq + Whisper</div>
</div>""", unsafe_allow_html=True)

# ── XP / Accuracy bar ─────────────────────────────────────────────────────────
xp_color = (
    "linear-gradient(90deg, #22c55e, #16a34a)"   if acc >= 80 else
    "linear-gradient(90deg, #f59e0b, #d97706)"   if acc >= 50 else
    "linear-gradient(90deg, #ef4444, #dc2626)"
)
xp_emoji = "🟢" if acc >= 80 else "🟡" if acc >= 50 else "🔴"
mode_icon = "🎙️" if st.session_state.study_mode == MODE_VOICE else "✍️"
st.markdown(f"""
<div class="fl-xp-wrap">
  <div class="fl-xp-header">
    <span>⚡ Session XP &nbsp;·&nbsp; {mode_icon} {st.session_state.study_mode.split(' ')[0]}</span>
    <span>{xp_emoji} {acc}% accuracy</span>
  </div>
  <div class="fl-xp-track">
    <div class="fl-xp-fill" style="width:{acc}%; background:{xp_color};"></div>
  </div>
  <div class="fl-xp-sub">
    <span>{st.session_state.total_exchanges} scambi completati</span>
    <span>{st.session_state.corrections} correzioni ricevute</span>
  </div>
  <div class="fl-xp-pills">
    <span class="fl-xp-pill">🎤 Whisper STT</span>
    <span class="fl-xp-pill">🧠 Groq LLM</span>
    <span class="fl-xp-pill">🔊 edge-tts</span>
  </div>
</div>""", unsafe_allow_html=True)


# ── Welcome / Topic picker ────────────────────────────────────────────────────
if st.session_state.topic is None:
    st.markdown("""
    <div class="fl-welcome-head">
      <div class="fl-welcome-eyebrow">Inizia ora</div>
      <div class="fl-welcome-title">Scegli uno scenario</div>
      <div class="fl-welcome-sub">
        Il tutor adatterà il linguaggio e il contesto.<br>Puoi cambiare scenario in qualsiasi momento.
      </div>
    </div>""", unsafe_allow_html=True)

    n_topics = len(TOPICS)
    for i, (name, meta) in enumerate(TOPICS.items()):
        first = i == 0
        last  = i == n_topics - 1

        # Pre-calcola CSS fuori dall'f-string per evitare parsing issues
        if first and last:
            radius = "8px"
        elif first:
            radius = "8px 8px 0 0"
        elif last:
            radius = "0 0 8px 8px"
        else:
            radius = "0"
        border_b = "none" if not last else "1px solid #e4e4e7"

        card_html = (
            f'<div class="fl-topic-row" style="border-radius:{radius};border-bottom:{border_b};">'
            f'<div class="fl-topic-icon">{meta["icon"]}</div>'
            f'<div class="fl-topic-info">'
            f'<div class="fl-topic-name">{name}</div>'
            f'<div class="fl-topic-desc">{meta["desc"]}</div>'
            f'</div>'
            f'<div class="fl-topic-arrow">&#8594;</div>'
            f'</div>'
        )

        col_card, col_btn = st.columns([5, 1])
        with col_card:
            st.markdown(card_html, unsafe_allow_html=True)
        with col_btn:
            st.markdown('<div style="margin-top:8px"></div>', unsafe_allow_html=True)
            btn_type = "primary" if name == "Free Talk" else "secondary"
            if st.button("Start", key=f"topic_{name}", type=btn_type, use_container_width=True):
                st.session_state.topic = name
                st.session_state.opener_played = False
                st.rerun()

    st.markdown(f"""
    <p style="font-size:.78rem; color:var(--ink-3); margin-top:1.5rem; text-align:center">
      Livello selezionato: {DIFFICULTIES[diff]} <strong>{diff}</strong>
      &nbsp;·&nbsp; modificabile dalla sidebar
    </p>""", unsafe_allow_html=True)


# ── Chat view ─────────────────────────────────────────────────────────────────
else:
    # Primo accesso al topic: il tutor apre la conversazione in personaggio
    if not st.session_state.opener_played:
        with st.spinner(f"Il tutor sta iniziando la conversazione…"):
            play_opener(active_topic)
        st.rerun()

    if st.session_state.messages:
        st.markdown('<div class="fl-chat">', unsafe_allow_html=True)
        for msg in st.session_state.messages:
            render_message(msg["role"], msg["content"], msg.get("correction"), msg.get("alternatives"))
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        meta = TOPICS[active_topic]
        st.markdown(f"""
        <div style="text-align:center; padding:2.5rem 0 1.5rem">
          <div style="font-size:2rem; margin-bottom:.6rem">{meta['icon']}</div>
          <div style="font-size:1.05rem; font-weight:700; letter-spacing:-.02em;
                      color:var(--ink); margin-bottom:.3rem">{active_topic}</div>
          <div style="font-size:.875rem; color:var(--ink-3)">{meta['desc']}</div>
          <div style="margin-top:1.5rem; font-size:.8rem; color:var(--ink-3)">
            Tieni premuto il microfono per iniziare 👇
          </div>
        </div>""", unsafe_allow_html=True)

    if st.session_state.study_mode == MODE_VOICE:
        # ── Modalità Fluency (Voice) ──────────────────────────────────────────
        # Autoplay risposta tutor
        if st.session_state.last_audio_file and os.path.exists(st.session_state.last_audio_file):
            autoplay(st.session_state.last_audio_file)

        # PTT button
        st.markdown('<div class="fl-ptt-area">', unsafe_allow_html=True)
        st.markdown('<span class="fl-ptt-hint">tieni premuto · rilascia per inviare · [Spazio]</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            ptt = push_to_talk_button(key="ptt")

        if ptt and isinstance(ptt, dict) and ptt.get("audio"):
            h = hash(ptt["audio"])
            if h != st.session_state.last_audio_hash:
                st.session_state.last_audio_hash = h
                run_pipeline(ptt["audio"])

    else:
        # ── Modalità Focus (Text & Drills) ────────────────────────────────────
        # Nessun autoplay, nessun PTT — solo chat testuale nativa Streamlit
        st.markdown(
            '<p style="text-align:center; font-size:.75rem; color:var(--ink-3); '
            'margin:.5rem 0 .25rem">✍️ Modalità Focus — niente audio, massima concentrazione</p>',
            unsafe_allow_html=True,
        )
        text_input = st.chat_input("Scrivi la tua risposta o l'esercizio qui...")
        if text_input:
            run_text_pipeline(text_input)

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<p style="text-align:center; font-size:.7rem; color:var(--ink-3);
   margin-top:3rem; letter-spacing:.02em">
  Fluency 01 &nbsp;·&nbsp; €0,00/mese &nbsp;·&nbsp; open-source stack
</p>""", unsafe_allow_html=True)
