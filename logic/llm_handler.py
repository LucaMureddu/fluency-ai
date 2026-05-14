"""
llm_handler.py
Gestione delle chiamate a Groq API (LLM Engine).
Implementa il Dual-Track Feedback con supporto per livelli di difficoltà
e modalità topic (spec §5).
"""

import os
import json
import re
import time
from groq import Groq
from dotenv import load_dotenv
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MAX_TOKENS   = int(os.getenv("MAX_TOKENS", 512))
TEMPERATURE  = float(os.getenv("TEMPERATURE", 0.7))
GROQ_MODEL   = "llama-3.1-8b-instant"


# ── Custom exception per Rate Limit ───────────────────────────────────────────
class GroqRateLimitError(Exception):
    """Sollevata quando Groq risponde con 429 / rate_limit."""
    pass

# ── Topic contexts ─────────────────────────────────────────────────────────────
TOPIC_CONTEXTS = {
    "Free Talk": (
        "Have a natural, open-ended conversation on any topic the student brings up. "
        "Be curious, ask follow-up questions, and keep things friendly and relaxed. "
        "You are simply a friendly native English speaker chatting with an Italian friend."
    ),
    "Job Interview": (
        "You are a professional HR recruiter conducting a job interview in English. "
        "Stay in character throughout: greet the candidate, ask typical interview questions "
        "(tell me about yourself, strengths, weaknesses, experience, salary expectations, "
        "why this company). React naturally to their answers as a real recruiter would. "
        "Be professional but friendly. Help the student sound confident and articulate."
    ),
    "Travel": (
        "You play different travel characters depending on context: airport check-in agent, "
        "hotel receptionist, taxi driver, café barista, or tourist information officer. "
        "Create realistic travel micro-scenarios. Ask the student for passport, booking refs, "
        "preferences. React to their answers naturally, as these real people would."
    ),
    "Restaurant": (
        "You are a friendly waiter/waitress at an English-speaking restaurant. Stay in character "
        "completely: greet the guest, hand them the menu, take their order, suggest dishes, "
        "handle special requests, check on satisfaction, present the bill. "
        "Use authentic restaurant language ('Are you ready to order?', 'How would you like your steak?', "
        "'Can I get you anything else?'). React naturally to whatever the student orders or asks."
    ),
    "Small Talk": (
        "You are a friendly native English speaker making casual conversation — like chatting "
        "with a colleague at the coffee machine or a neighbour. Topics: weather, weekend plans, "
        "sports, TV shows, local news, food, travel. Keep it light, spontaneous and fun. "
        "Use natural fillers, contractions and colloquial expressions native speakers actually use."
    ),
}

# ── Opening messages per topic ─────────────────────────────────────────────────
# Queste sono le prime battute del tutor quando l'utente seleziona uno scenario.
# Sono hardcoded per latenza zero — il tutor inizia subito in personaggio.
TOPIC_OPENERS = {
    "Free Talk": (
        "Hey! Great to have you here. I'm your English tutor — think of me as a native "
        "speaker friend. So, what's on your mind today? Tell me anything!"
    ),
    "Job Interview": (
        "Good morning! Please, come in and take a seat. I'm Sarah from HR — lovely to meet you. "
        "So, before we dive in, could you start by telling me a little about yourself "
        "and what brought you to apply for this position?"
    ),
    "Travel": (
        "Good morning! Welcome to Heathrow Airport. I'm at the check-in desk. "
        "Could I see your passport and booking reference, please? "
        "And are you checking in any luggage today?"
    ),
    "Restaurant": (
        "Good evening! Welcome to The Crown. I'll be your server tonight — my name's James. "
        "Can I start you off with something to drink while you look at the menu?"
    ),
    "Small Talk": (
        "Hey! Crazy weather we've been having lately, right? "
        "I feel like it changes every five minutes! How's your day going so far?"
    ),
}

# ── Difficulty settings ────────────────────────────────────────────────────────
DIFFICULTY_SETTINGS = {
    "Beginner": {
        "reply_instruction": (
            "Use simple vocabulary and short sentences (max 2 sentences). "
            "Be very encouraging and patient. Speak slowly and clearly in your replies."
        ),
        "correction_instruction": (
            "Correct ONLY major errors that make the sentence hard to understand "
            "(wrong verb tense, completely wrong word). Ignore minor mistakes. "
            "The correction must be very simple, in Italian, max 1 short sentence."
        ),
    },
    "Intermediate": {
        "reply_instruction": (
            "Use natural vocabulary and 2-3 sentences. Balance simplicity with expressiveness. "
            "Introduce idiomatic phrases naturally in your reply when appropriate."
        ),
        "correction_instruction": (
            "Correct real grammar errors (verb tense, verb form after modal verbs, "
            "wrong prepositions, article mistakes). In Italian, explain the rule briefly."
        ),
    },
    "Advanced": {
        "reply_instruction": (
            "Use rich, varied vocabulary and natural idiomatic English. "
            "Replies can be 2-4 sentences. Challenge the student with complex structures, "
            "phrasal verbs, and advanced expressions."
        ),
        "correction_instruction": (
            "Correct grammar errors AND unnatural phrasing / non-idiomatic expressions. "
            "Point out when something is grammatically correct but sounds unnatural to a native speaker. "
            "In Italian, explain both the error and the more natural alternative."
        ),
    },
}


def _build_regional_instruction(voice_model: str) -> str:
    """
    Restituisce l'istruzione di variante regionale dell'inglese
    in base al modello TTS selezionato.
    """
    if "en-GB" in voice_model:
        return (
            "REGIONAL ENGLISH: You must use British English spelling and vocabulary "
            "(e.g., 'flat' not 'apartment', 'lift' not 'elevator', 'queue' not 'line', "
            "'biscuit' not 'cookie', 'lorry' not 'truck'). "
            "Use British idioms and expressions naturally (e.g., 'cheers', 'brilliant', 'quite'). "
            "British spelling rules apply: -ise not -ize, -our not -or (colour, favour), -re not -er (centre, theatre)."
        )
    if "en-AU" in voice_model:
        return (
            "REGIONAL ENGLISH: You must use Australian English vocabulary and casual tone. "
            "Use Australian slang naturally where appropriate (e.g., 'mate', 'no worries', "
            "'arvo' for afternoon, 'reckon', 'heaps' for very/a lot). "
            "Keep it friendly and relaxed — Australians are informal even in professional contexts."
        )
    # Default: en-US or any unrecognised locale
    return (
        "REGIONAL ENGLISH: Use standard American English spelling and vocabulary "
        "(e.g., 'apartment', 'elevator', 'color', 'favorite'). "
        "Use natural American expressions and idioms."
    )


def build_system_prompt(
    difficulty: str = "Intermediate",
    topic: str = "Free Talk",
    voice_model: str = "",
    study_mode: str = "",
) -> str:
    """
    Costruisce il system prompt dinamicamente.
    - Modalità Fluency (Voice): conversazione naturale, correzione singola, TTS-friendly.
    - Modalità Focus (Text & Drills): analisi grammaticale profonda, alternative, micro-esercizi.
    """

    # ── Modalità Focus: prompt completamente diverso ──────────────────────────
    if study_mode == "✍️ Focus (Text & Drills)":
        diff = DIFFICULTY_SETTINGS.get(difficulty, DIFFICULTY_SETTINGS["Intermediate"])
        return f"""You are an expert English grammar professor working with an Italian student at {difficulty} level.

Your role is to give deep, educational feedback — not just chat. Every response must be a teaching moment.

You MUST output ONLY a valid JSON object with EXACTLY these three keys:
{{"correction": "...", "alternatives": "...", "reply": "..."}}

--- OUTPUT FORMAT (CRITICAL) ---
- Output ONLY the raw JSON. No markdown, no code blocks, no text outside the JSON.
- NEVER put real newline characters inside a JSON string value. Use a space instead.
- NEVER use double quotes inside string values; use single quotes if needed.

--- CORRECTION (key: "correction") ---
If the student's sentence has grammar errors, provide a detailed explanation IN ITALIAN:
1. Quote the exact wrong phrase
2. Name the specific grammar rule being broken (e.g. 'Present Perfect vs Simple Past', 'Gerund after verbs of preference')
3. Explain WHY it is wrong — the underlying rule, with a brief example
4. Give the corrected version
Difficulty level for depth: {diff["correction_instruction"]}
If there are NO errors, set correction to null. Never invent corrections.

--- ALTERNATIVES (key: "alternatives") ---
Always provide this, even if there are no errors.
Give 2 or 3 alternative phrasings that a native speaker would use to express the same idea more naturally or with more variety.
Format in Italian, showing each alternative clearly:
Example: 'Un madrelingua potrebbe dire: (1) "I spent last summer in Spain" (2) "I was in Spain last summer" (3) "I had the chance to visit Spain last summer"'
If the sentence is already perfect and natural, say: 'La frase e' ottima! Ecco alcune varianti stilistiche: ...'

--- REPLY (key: "reply") ---
First, continue the conversation naturally in English (1-2 sentences).
Then, add a quick micro-exercise to reinforce the grammar rule you just explained (or a related rule if there was no error).
Micro-exercise formats (vary them):
- Fill-in-the-gap: 'Quick drill: complete the sentence: I ___ (go) to London last year.'
- Translation: 'Now try in English: Sono andato al supermercato ieri.'
- Error correction: 'Spot the mistake: She have been waiting for an hour.'
- Open question targeting the rule: 'Tell me about something you did last weekend — practise the Simple Past!'

--- VALID OUTPUT EXAMPLE ---
{{"correction": "Hai detto 'last summer I go to Spain': il Simple Past e' obbligatorio per azioni completate nel passato. 'Go' e' il presente; la forma corretta e' 'went'. Corretto: 'last summer I went to Spain'.", "alternatives": "Un madrelingua potrebbe dire: (1) 'I spent last summer in Spain' (2) 'I was in Spain last summer' (3) 'Last summer I had the chance to visit Spain'", "reply": "Spain sounds amazing! Great food and culture. Quick drill — complete the sentence: 'Last year, I ___ (visit) three different countries.'"}}"""

    # ── Modalità Fluency (Voice): prompt conversazionale standard ─────────────
    diff        = DIFFICULTY_SETTINGS.get(difficulty, DIFFICULTY_SETTINGS["Intermediate"])
    topic_ctx   = TOPIC_CONTEXTS.get(topic, TOPIC_CONTEXTS["Free Talk"])
    regional    = _build_regional_instruction(voice_model or os.getenv("VOICE_MODEL", "en-US-GuyNeural"))

    return f"""You are an encouraging English tutor helping an Italian student practice English.

SCENARIO: {topic_ctx}

DIFFICULTY LEVEL: {difficulty}
- Reply style: {diff["reply_instruction"]}
- Correction style: {diff["correction_instruction"]}

{regional}

You MUST always respond with a single valid JSON object with EXACTLY these two keys:
{{"correction": "...", "reply": "..."}}

--- OUTPUT FORMAT (CRITICAL) ---
- Output ONLY the raw JSON. No markdown, no code blocks, no text outside the JSON.
- NEVER put real newline characters inside a JSON string value. Use a space instead.
- NEVER use double quotes inside string values; use single quotes if needed.

--- REPLY RULES ---
- Always reply in English. Follow the difficulty reply style above.
- Apply the REGIONAL ENGLISH rules above consistently in every reply.
- If the student writes mostly in Italian: reply in English saying you noticed they switched languages and ask them to try again in English. Example: "It looks like you switched to Italian there! Try to say that again in English - you can do it!"

--- CORRECTION RULES ---
Follow the difficulty correction style above. Additionally:

PRIORITY ORDER for corrections:
1. VERB TENSE errors (present used instead of past: "today I create" → "today I created", "last summer I go" → "last summer I went")
2. VERB FORM after stative/modal verbs ("I love play" → "I love playing", "I prefer go" → "I prefer to go")
3. PREPOSITIONS with fixed rules ("arrived to" → "arrived in/at")
4. ARTICLES and PLURAL ("I am developer" → "I am a developer", "a lot of city" → "cities")

Correct ONE error per message (the highest priority one found).

CORRECTION FORMAT in Italian:
1. Quote the exact wrong phrase: 'Hai detto "..."'
2. Explain the rule (one sentence max)
3. Give correct version: 'Corretto: "..."'
Example: 'Hai detto "last summer I go to Spain": per eventi passati usa il Simple Past. Corretto: "last summer I went to Spain".'

If NO error from the priority list exists, set correction to null. Never invent corrections.

--- VALID OUTPUT EXAMPLES ---
{{"correction": null, "reply": "That sounds amazing! What was your favourite part of the trip?"}}
{{"correction": "Hai detto \\"I prefer go outside\\": dopo 'prefer' si usa l'infinito con 'to' o la forma in -ing. Corretto: \\"I prefer to go outside\\".", "reply": "Great attitude! Going outside is always refreshing. Where do you usually go?"}}"""


def get_groq_client() -> Groq:
    if not GROQ_API_KEY or GROQ_API_KEY == "tuo_codice_api_qui":
        raise ValueError("GROQ_API_KEY non configurata. Inserisci la tua chiave nel file .env")
    return Groq(api_key=GROQ_API_KEY)


def build_messages(
    chat_history: list[dict],
    user_input: str,
    difficulty: str,
    topic: str,
    voice_model: str = "",
    study_mode: str = "",
) -> list[dict]:
    messages = [{"role": "system", "content": build_system_prompt(difficulty, topic, voice_model, study_mode)}]
    for msg in chat_history[-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})
    return messages


def _safe_parse_json(raw: str) -> dict:
    """Parsing JSON robusto con repair progressivo a 4 livelli."""

    # Livello 1: parsing diretto
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Livello 2: estrai blocco { ... }
    start_idx = raw.find("{")
    end_idx   = raw.rfind("}") + 1
    if start_idx == -1 or end_idx <= start_idx:
        raise ValueError(f"Nessun oggetto JSON trovato: {raw}")
    candidate = raw[start_idx:end_idx]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Livello 3: pulizia newline dentro le stringhe
    cleaned = re.sub(r'(?<!\\)\n', ' ', candidate)
    cleaned = re.sub(r'(?<!\\)\r', ' ', cleaned)
    cleaned = re.sub(r'  +', ' ', cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Livello 4: estrazione regex come ultimo resort
    # Gestisce sia il formato dual-track (Fluency) che triple-track (Focus)
    correction_match   = re.search(r'"correction"\s*:\s*(?:null|"((?:[^"\\]|\\.)*)")', cleaned)
    alternatives_match = re.search(r'"alternatives"\s*:\s*(?:null|"((?:[^"\\]|\\.)*)")', cleaned)
    reply_match        = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)

    if reply_match:
        correction   = correction_match.group(1)   if (correction_match   and correction_match.group(1))   else None
        alternatives = alternatives_match.group(1) if (alternatives_match and alternatives_match.group(1)) else None
        result = {"correction": correction, "reply": reply_match.group(1)}
        if alternatives is not None:
            result["alternatives"] = alternatives
        return result

    raise ValueError(f"Impossibile fare il parsing della risposta JSON: {raw}")


@retry(
    retry=retry_if_exception_type(GroqRateLimitError),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def call_llm(
    chat_history: list[dict],
    user_input: str,
    difficulty: str = "Intermediate",
    topic: str = "Free Talk",
    voice_model: str = "",
    study_mode: str = "",
) -> dict:
    """
    Chiama Groq e restituisce il JSON dual-track (Fluency) o triple-track (Focus).
    Latenza target: < 300ms (spec §8).
    Retry automatico (max 3 tentativi) in caso di Rate Limit 429.
    Il system prompt varia radicalmente in base alla study_mode.
    """
    client   = get_groq_client()
    messages = build_messages(chat_history, user_input, difficulty, topic, voice_model, study_mode)

    start = time.time()
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        err_str = str(e).lower()
        # Rate limit: rilancia GroqRateLimitError → tenacity riproverà
        if "429" in err_str or "rate_limit" in err_str or "too many requests" in err_str:
            attempt_num = getattr(call_llm.statistics, "attempt_number", "?")
            print(f"[LLM] Rate limit rilevato (tentativo {attempt_num}/3). Attendo prima di riprovare…")
            raise GroqRateLimitError(str(e)) from e
        # Qualsiasi altro errore di rete/API → fallimento immediato
        raise RuntimeError(f"Errore chiamata Groq API: {e}") from e

    elapsed = (time.time() - start) * 1000
    raw     = response.choices[0].message.content.strip()
    print(f"[LLM] Risposta in {elapsed:.0f}ms [{difficulty}/{topic}]: {raw}")

    parsed = _safe_parse_json(raw)

    if "reply" not in parsed:
        raise ValueError(f"JSON manca della chiave 'reply': {parsed}")

    parsed["correction"]   = parsed.get("correction")   or None
    parsed["alternatives"] = parsed.get("alternatives") or None
    return parsed
