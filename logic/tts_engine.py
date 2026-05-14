"""
tts_engine.py
Interfacciamento con edge-tts per la sintesi vocale (TTS).
Utilizza le voci neurali Microsoft Edge (en-US-GuyNeural).
Latenza target: < 600ms (spec §8).
"""

import os
import time
import asyncio
import tempfile
import edge_tts
from dotenv import load_dotenv

load_dotenv()

VOICE_MODEL = os.getenv("VOICE_MODEL", "en-US-GuyNeural")


async def _synthesize_async(text: str, output_path: str) -> None:
    """
    Funzione asincrona interna per la generazione audio via edge-tts.

    Args:
        text: testo in inglese da sintetizzare.
        output_path: percorso dove salvare il file MP3.
    """
    communicate = edge_tts.Communicate(text, VOICE_MODEL)
    await communicate.save(output_path)


def synthesize_speech(text: str, output_path: str | None = None) -> str:
    """
    Genera un file MP3 dal testo fornito usando edge-tts.

    Args:
        text: testo in inglese da convertire in voce.
        output_path: percorso opzionale per il file MP3.
                     Se None, crea un file temporaneo.

    Returns:
        Percorso al file MP3 generato.
        Latenza target: < 600ms (spec §8).
    """
    if not text or not text.strip():
        raise ValueError("Il testo per la sintesi vocale è vuoto.")

    # Crea un file temporaneo se non è stato specificato un percorso
    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False, prefix="fluency_tts_"
        )
        output_path = tmp.name
        tmp.close()

    start = time.time()

    # Streamlit gira in un thread con un event loop già attivo.
    # La soluzione robusta è sempre eseguire la coroutine in un thread separato
    # con un event loop fresco — evita conflitti sia in Streamlit che in script.
    import concurrent.futures

    def _run_in_thread():
        # Ogni thread ha il suo event loop isolato
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_synthesize_async(text, output_path))
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_in_thread)
        future.result()  # Propaga eventuali eccezioni

    elapsed = (time.time() - start) * 1000
    print(f"[TTS] Audio generato in {elapsed:.0f}ms → {output_path}")

    return output_path


def get_available_voices() -> list[str]:
    """
    Ritorna una lista di voci en-US disponibili per edge-tts.
    Utile per eventuali impostazioni future nella UI.
    """
    voices = [
        "en-US-GuyNeural",
        "en-US-JennyNeural",
        "en-US-AriaNeural",
        "en-GB-RyanNeural",
        "en-AU-NatashaNeural",
    ]
    return voices
