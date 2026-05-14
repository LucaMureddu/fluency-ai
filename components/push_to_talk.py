"""
push_to_talk.py
Wrapper Python per il componente Push-to-Talk custom di Fluency 01.
Restituisce un dict {"audio": "<base64_wav>", "mimeType": "audio/wav"}
quando l'utente registra e rilascia il tasto.
"""

import os
import streamlit.components.v1 as components

_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptt_frontend")

_push_to_talk = components.declare_component(
    "push_to_talk",
    path=_COMPONENT_DIR,
)


def push_to_talk_button(key: str = "ptt") -> dict | None:
    """
    Renderizza il pulsante Push-to-Talk.

    Returns:
        dict {"audio": base64_string, "mimeType": "audio/wav"} quando
        l'utente ha finito di registrare, oppure None se in attesa.
    """
    return _push_to_talk(key=key, default=None)
