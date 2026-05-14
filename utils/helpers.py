"""
helpers.py
Funzioni di utility per la gestione dei file temporanei e il cleanup.
Previene la saturazione dello storage locale (spec §6 - Cleanup).
"""

import os
import glob
import tempfile
import base64
import csv
import io
from datetime import datetime


# Prefisso usato per identificare i file temporanei di Fluency
TEMP_PREFIX = "fluency_"


def save_audio_bytes(audio_bytes: bytes, suffix: str = ".wav") -> str:
    """
    Salva i bytes audio in un file temporaneo.

    Args:
        audio_bytes: dati audio grezzi (WAV da audio_recorder_streamlit).
        suffix: estensione del file (.wav o .mp3).

    Returns:
        Percorso al file temporaneo creato.
    """
    tmp = tempfile.NamedTemporaryFile(
        suffix=suffix,
        delete=False,
        prefix=TEMP_PREFIX,
    )
    tmp.write(audio_bytes)
    tmp.close()
    return tmp.name


def delete_file(path: str | None) -> None:
    """
    Elimina un singolo file in modo sicuro (ignora errori se non esiste).

    Args:
        path: percorso al file da eliminare.
    """
    if path and os.path.exists(path):
        try:
            os.remove(path)
            print(f"[Cleanup] File eliminato: {path}")
        except OSError as e:
            print(f"[Cleanup] Impossibile eliminare {path}: {e}")


def cleanup_temp_files() -> int:
    """
    Elimina tutti i file temporanei di Fluency (WAV e MP3) nella cartella temp.
    Da chiamare all'avvio della sessione o alla sua chiusura.

    Returns:
        Numero di file eliminati.
    """
    temp_dir = tempfile.gettempdir()
    pattern_wav = os.path.join(temp_dir, f"{TEMP_PREFIX}*.wav")
    pattern_mp3 = os.path.join(temp_dir, f"{TEMP_PREFIX}*.mp3")

    files = glob.glob(pattern_wav) + glob.glob(pattern_mp3)
    count = 0
    for f in files:
        try:
            os.remove(f)
            count += 1
        except OSError:
            pass

    if count > 0:
        print(f"[Cleanup] Eliminati {count} file temporanei.")
    return count


def audio_file_to_base64(path: str) -> str:
    """
    Converte un file audio in stringa base64 per l'autoplay HTML.

    Args:
        path: percorso al file MP3.

    Returns:
        Stringa base64 del file audio.
    """
    with open(path, "rb") as f:
        audio_bytes = f.read()
    return base64.b64encode(audio_bytes).decode("utf-8")


def format_correction_message(correction: str | None) -> str | None:
    """
    Formatta il messaggio di correzione per la visualizzazione in UI.

    Args:
        correction: testo della correzione o None.

    Returns:
        Stringa formattata o None se non c'è correzione.
    """
    if not correction:
        return None
    return f"💡 {correction}"


def generate_anki_csv(messages: list) -> str:
    """
    Genera una stringa CSV compatibile con Anki a partire dalla cronologia messaggi.

    Formato Anki: delimitatore `;`, due colonne:
        - Fronte: la frase sbagliata detta dall'utente
        - Retro:  la correzione fornita dal tutor

    Args:
        messages: lista di dict con chiavi role, content, correction (opzionale).

    Returns:
        Stringa CSV pronta per il download (encoding UTF-8 con BOM per Excel).
    """
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")

    for msg in messages:
        if msg.get("role") != "user":
            continue
        raw_correction = msg.get("correction")
        if not raw_correction:
            continue

        # Rimuovi prefisso emoji aggiunto da format_correction_message
        correction_clean = raw_correction.lstrip("💡 ").strip()
        front = msg.get("content", "").strip()

        if front and correction_clean:
            writer.writerow([front, correction_clean])

    csv_str = output.getvalue()
    output.close()

    # Prefisso BOM UTF-8: garantisce apertura corretta in Excel e Anki
    return "﻿" + csv_str


def generate_session_report(session_state) -> str:
    """
    Genera un report Markdown della sessione di pratica.

    Include statistiche, tabella degli errori e timestamp.
    Compatibile con qualsiasi viewer Markdown (Obsidian, Notion, VS Code, ecc.).

    Args:
        session_state: oggetto st.session_state di Streamlit.

    Returns:
        Stringa Markdown pronta per il download.
    """
    now         = datetime.now()
    date_str    = now.strftime("%d %B %Y")
    time_str    = now.strftime("%H:%M")
    topic       = getattr(session_state, "topic", "Free Talk") or "Free Talk"
    difficulty  = getattr(session_state, "difficulty", "Intermediate")
    exchanges   = getattr(session_state, "total_exchanges", 0)
    corrections = getattr(session_state, "corrections", 0)
    messages    = getattr(session_state, "messages", [])

    acc = round((1 - corrections / exchanges) * 100) if exchanges else 100

    # ── Intestazione ──────────────────────────────────────────────────────────
    lines = [
        "# Fluency 01 — Session Report",
        "",
        f"> 📅 **{date_str}** &nbsp;·&nbsp; 🕐 **{time_str}**",
        f"> 🎭 Scenario: **{topic}** &nbsp;·&nbsp; 📊 Livello: **{difficulty}**",
        "",
        "---",
        "",
        "## Statistiche sessione",
        "",
        "| Metrica | Valore |",
        "|---|---|",
        f"| Scambi totali | **{exchanges}** |",
        f"| Correzioni ricevute | **{corrections}** |",
        f"| Accuracy | **{acc}%** |",
        "",
        "---",
        "",
    ]

    # ── Tabella errori ────────────────────────────────────────────────────────
    errors = [
        msg for msg in messages
        if msg.get("role") == "user" and msg.get("correction")
    ]

    if errors:
        lines += [
            "## Errori e correzioni",
            "",
            "| # | Frase originale | Correzione |",
            "|---|---|---|",
        ]
        for i, msg in enumerate(errors, 1):
            original   = msg.get("content", "").strip().replace("|", "\\|")
            correction = msg.get("correction", "").lstrip("💡 ").strip().replace("|", "\\|")
            lines.append(f"| {i} | {original} | {correction} |")

        lines += [
            "",
            "---",
            "",
            "## Flashcard suggerite",
            "",
            "_Importa il file `fluency_flashcards.csv` in **Anki** per memorizzare le correzioni._",
            "",
        ]
    else:
        lines += [
            "## Errori e correzioni",
            "",
            "_Nessun errore rilevato in questa sessione — ottimo lavoro! 🎉_",
            "",
            "---",
            "",
        ]

    # ── Footer ─────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "_Report generato da **Fluency 01** · Stack: Groq + Whisper + edge-tts · Costo: €0,00_",
    ]

    return "\n".join(lines)
