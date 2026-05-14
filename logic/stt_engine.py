"""
stt_engine.py
Gestione del modello faster-whisper per la trascrizione audio locale.
Il modello viene caricato una sola volta grazie a @st.cache_resource.
"""

import os
import time
import streamlit as st
from faster_whisper import WhisperModel
from dotenv import load_dotenv

load_dotenv()

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")


@st.cache_resource(show_spinner=False)
def load_whisper_model() -> WhisperModel:
    """
    Carica il modello Whisper in locale e lo mantiene in cache.
    Evita il ricaricamento ad ogni interazione (requisito spec §6).
    Target: modello 'base' o 'small' su CPU moderna.
    """
    model = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type="int8",   # ottimizzazione per CPU
    )
    return model


def transcribe_audio(audio_path: str) -> str:
    """
    Trascrive un file audio WAV in testo inglese.

    Args:
        audio_path: percorso al file WAV registrato.

    Returns:
        Stringa con il testo trascritto.
        Latenza target: < 500ms (spec §8).
    """
    model = load_whisper_model()

    start = time.time()
    segments, info = model.transcribe(
        audio_path,
        language="en",          # forza il riconoscimento in inglese
        beam_size=5,            # più alto = più accurato (era 1, era veloce ma impreciso)
        vad_filter=True,        # rimuove silenzi iniziali/finali
        vad_parameters={"min_silence_duration_ms": 500},
        # initial_prompt aiuta Whisper a capire il contesto e non confondere
        # parole italiane con inglesi (es. "Torino" → "Turinus")
        initial_prompt=(
            "This is an English conversation practice session. "
            "The speaker is an Italian learning English. "
            "Proper nouns may include: Juventus, Milan, Italy, Luca. "
            "Transcribe exactly what is said in English."
        ),
    )

    transcript = " ".join(segment.text.strip() for segment in segments)
    elapsed = (time.time() - start) * 1000
    print(f"[STT] Trascrizione completata in {elapsed:.0f}ms: '{transcript}'")

    return transcript.strip()
