"""
LLM Handler — Dual-Provider Engine for Temporal Resonance
=========================================================
Supports two provider modes:
  - "ollama": Local Ollama instance with native JSON schema enforcement
  - "api":    Any OpenAI-compatible API (Gemini, OpenAI, Anthropic, Groq, etc.)

API keys are loaded ONLY from environment variables or a project-local .env file.
They are never stored in game_state.json or source code.

The extraction pipeline guarantees the game loop always receives a valid response
dict, even if the model produces garbage, thinking blocks, or nothing at all.
"""

import urllib.request
import urllib.error
import json
import os
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


# ── Pydantic Response Schema ──────────────────────────────────────────────────

class SaifResponse(BaseModel):
    """Strict contract for LLM output. Used for schema enforcement and validation."""
    dialogue: str = Field(
        description="The spoken line of dialogue from Saif, staying in character."
    )
    respect_change: Literal[-10, 0, 10] = Field(
        description="The integer change in respect: must be exactly -10, 0, or 10."
    )


# ── Safe Fallback ─────────────────────────────────────────────────────────────

SAFE_FALLBACK: dict = {
    "dialogue": "...(Saif stares into the distance, silent)...",
    "respect_change": 0
}


# ── .env File Loader ──────────────────────────────────────────────────────────

def load_env_file(env_path: str = None) -> None:
    """
    Loads KEY=VALUE pairs from a .env file into os.environ.
    Skips comments (#) and blank lines. Does not override existing env vars.
    This avoids adding python-dotenv as a dependency.
    """
    if env_path is None:
        # Look for .env in project root (two levels up from engine/)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(project_root, ".env")

    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip surrounding quotes if present
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                # Do not override existing environment variables
                if key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(f"[LLM System] Warning: Could not read .env file: {e}")


def save_api_key_to_env(api_key: str, env_path: str = None) -> None:
    """
    Saves or updates the API_KEY entry in the project .env file.
    Creates the file if it doesn't exist. Never stores keys in game_state.json.
    """
    if env_path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env_path = os.path.join(project_root, ".env")

    lines = []
    key_found = False

    if os.path.exists(env_path):
        try:
            with open(env_path, "r") as f:
                for line in f:
                    if line.strip().startswith("API_KEY="):
                        lines.append(f'API_KEY="{api_key}"\n')
                        key_found = True
                    else:
                        lines.append(line)
        except Exception:
            pass

    if not key_found:
        lines.append(f'API_KEY="{api_key}"\n')

    try:
        with open(env_path, "w") as f:
            f.writelines(lines)
        # Also set it in the current process environment
        os.environ["API_KEY"] = api_key
        print("[LLM System] API key saved to .env file (gitignored).")
    except Exception as e:
        print(f"[LLM System] Warning: Could not save .env file: {e}")


# Load .env on module import
load_env_file()


# ── JSON Extraction Pipeline ─────────────────────────────────────────────────

def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks that thinking models emit."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """
    Strip markdown code fences (```json ... ``` or ``` ... ```).
    Extracts only the content inside the fences.
    """
    # Try to find fenced code block content
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _find_json_by_brace_depth(text: str) -> str | None:
    """
    Locate the outermost complete JSON object using brace-depth counting.
    Correctly handles braces inside string literals.

    Returns the JSON substring or None if no complete object found.
    """
    start = None
    depth = 0
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if ch == "\\":
            if in_string:
                escape_next = True
            continue

        if ch == '"':
            if not in_string and depth > 0:
                in_string = True
            elif in_string:
                in_string = False
            elif not in_string and depth == 0 and start is not None:
                # Quote outside of any object — skip
                pass
            continue

        if in_string:
            continue

        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start : i + 1]

    return None


def _clamp_respect(value) -> int:
    """Clamp respect_change to nearest valid value (-10, 0, or 10)."""
    try:
        val = int(value)
    except (TypeError, ValueError):
        return 0

    if val > 0:
        return 10
    elif val < 0:
        return -10
    return 0


def extract_json_payload(raw_text: str) -> dict:
    """
    Bulletproof JSON extraction pipeline:
    1. Strip <think>...</think> blocks
    2. Strip markdown code fences
    3. Find outermost JSON object via brace-depth counting
    4. Parse via json.loads()
    5. Validate against SaifResponse Pydantic schema
    6. Return clean dict or SAFE_FALLBACK — NEVER returns None

    This handles frontier models that emit thousands of words of reasoning,
    thinking blocks with JSON fragments, markdown formatting, and conversational
    padding around the actual JSON response.
    """
    if not raw_text or not raw_text.strip():
        print("[LLM Extractor] Empty response received.")
        return SAFE_FALLBACK.copy()

    # Step 1: Strip thinking blocks
    cleaned = _strip_think_blocks(raw_text)

    # Step 2: Strip markdown fences
    cleaned = _strip_markdown_fences(cleaned)

    # Step 3: Find JSON via brace-depth matching
    json_str = _find_json_by_brace_depth(cleaned)
    if not json_str:
        print("[LLM Extractor] No JSON object found in response.")
        print(f"  Cleaned text was: {cleaned[:200]}...")
        return SAFE_FALLBACK.copy()

    # Step 4: Parse JSON
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"[LLM Extractor] JSON decode failed: {e}")
        print(f"  Attempted to parse: {json_str[:200]}...")
        return SAFE_FALLBACK.copy()

    # Step 5: Validate against Pydantic schema
    try:
        validated = SaifResponse(**parsed)
        return validated.model_dump()
    except ValidationError:
        # Try to salvage — extract what we can and clamp values
        dialogue = parsed.get("dialogue")
        respect = parsed.get("respect_change")

        if isinstance(dialogue, str) and dialogue.strip():
            return {
                "dialogue": dialogue.strip(),
                "respect_change": _clamp_respect(respect)
            }

        print(f"[LLM Extractor] Pydantic validation failed. Parsed: {parsed}")
        return SAFE_FALLBACK.copy()


# ── Prompt Construction ───────────────────────────────────────────────────────

def _build_world_context(global_flags: dict) -> str:
    """Reads the global_flags dictionary and converts active flags into a single concise World Context string."""
    if not global_flags:
        return "World Context: The player has not yet started the desert quest."
        
    started = global_flags.get("started_desert_quest", False)
    defeated = global_flags.get("desert_boss_defeated", False)
    
    if started and not defeated:
        return "World Context: The player has started the desert quest but the boss is still alive."
    elif started and defeated:
        return "World Context: The player has completed the desert quest and the boss is defeated."
    else:
        return "World Context: The player has not yet started the desert quest."

def _build_system_prompt(saif_respect: int, player_hp: int, enemy_hp: int,
                         in_combat: bool, current_location: str = "overworld") -> str:
    """Build the character system prompt with dynamic game state injection."""
    core_desc = "You are Saif, a weary, pragmatic, and tactical warrior. Speak conversationally and directly. NEVER use poetic metaphors about the desert, sand, or the sun. Do not be overly dramatic. Use modern, grounded syntax. Pay close attention to the World Context at the very beginning of the prompt to understand active narrative events and whether bosses have been defeated."
    
    if current_location == 'combat':
        context = f"{core_desc} You are currently in a deadly battle. Keep your words sharp, tactical, and focused on survival. Your respect for the player is {saif_respect}/100."
    elif current_location == 'camp':
        context = f"{core_desc} You are currently resting safely at camp by a warm fire. The danger has passed. You are relaxed, reflective, and much more open to sharing deep lore, your history, and your personal thoughts. Your respect for the player is {saif_respect}/100."
    else: # 'overworld'
        context = f"{core_desc} You are currently exploring the dangerous overworld. You are cautious and watching for ambushes. Your respect for the player is {saif_respect}/100."

    rules = (
        "\n\nRespond in 1 or 2 short sentences, staying in character.\n\n"
        "RESPECT RULES (you MUST follow these exactly):\n"
        "- If the player speaks bravely, respectfully, appeals to honor/duty, "
        "or offers genuine help → respect_change: 10\n"
        "- If the player insults you, acts cowardly, complains, shows weakness, "
        "or disrespects you → respect_change: -10\n"
        "- If the player's message is neutral, a simple question, or small talk "
        "→ respect_change: 0\n\n"
        "You MUST pick exactly one of: -10, 0, or 10. No other values.\n\n"
        "You MUST respond with ONLY a JSON object matching this exact schema:\n"
        '{"dialogue": "Your reply as Saif", "respect_change": <-10 or 0 or 10>}\n'
        "Do NOT include any other text, explanation, or markdown. ONLY the JSON object."
    )

    return context + rules


def _build_user_prompt(player_text: str, chat_history: list) -> str:
    """Build the user message with rolling chat history context."""
    history_str = ""
    if chat_history:
        history_str = "Recent Chat History:\n"
        for exchange in chat_history:
            if len(exchange) == 2:
                history_str += f'Player: "{exchange[0]}"\nSaif: "{exchange[1]}"\n'
        history_str += "\n"

    return (
        f"{history_str}"
        f'Player says: "{player_text}"\n\n'
        'Respond with ONLY the JSON object. No other text.'
    )


# ── Provider Implementations ─────────────────────────────────────────────────

def _call_ollama(system_prompt: str, user_prompt: str,
                 model: str, base_url: str, think: bool) -> str | None:
    """
    Call local Ollama using the native /api/chat endpoint.
    Uses structured JSON schema enforcement via the 'format' parameter.
    """
    url = f"{base_url.rstrip('/')}/api/chat"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "format": SaifResponse.model_json_schema(),
        "think": think,
        "stream": False,
        "options": {
            "temperature": 0.5
        }
    }

    print(f"\n=== [Ollama Request] ===")
    print(f"  Model: {model} | Think: {think}")
    print(f"  URL: {url}")
    # Print the prepended World Context / first part of system prompt
    context_line = system_prompt.split("\n")[0] if "\n" in system_prompt else system_prompt
    print(f"  {context_line}")
    print(f"========================\n")

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        # Thinking models + cold model loads can take 2-3+ minutes
        print("[LLM System] Waiting for Ollama response (game will resume when ready)...")
        with urllib.request.urlopen(req, timeout=300) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)

            print(f"=== [Ollama Response] ===")
            # Print thinking content if present
            thinking = res_json.get("message", {}).get("thinking")
            if thinking:
                print(f"  Thinking: {thinking[:200]}...")
            content = res_json.get("message", {}).get("content", "")
            print(f"  Content: {content[:300]}")
            print(f"=========================\n")

            return content

    except urllib.error.URLError as e:
        print(f"[LLM System] Ollama connection failed: {e}")
        print(f"  Is Ollama running at {base_url}?")
    except Exception as e:
        print(f"[LLM System] Ollama request failed: {e}")

    return None


def _call_api(system_prompt: str, user_prompt: str,
              model: str, base_url: str, api_key: str) -> str | None:
    """
    Call any OpenAI-compatible API endpoint.
    Works with Gemini, OpenAI, Anthropic (via compatible endpoint), Groq, etc.
    """
    url = f"{base_url.rstrip('/')}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.5,
        "response_format": {"type": "json_object"}
    }

    print(f"\n=== [API Request] ===")
    print(f"  Model: {model}")
    print(f"  URL: {url}")
    context_line = system_prompt.split("\n")[0] if "\n" in system_prompt else system_prompt
    print(f"  {context_line}")
    # TODO(security): Never log the API key
    print(f"  Key: {'*' * 8}...{api_key[-4:] if len(api_key) > 4 else '****'}")
    print(f"=====================\n")

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)

            print(f"=== [API Response] ===")
            print(f"  Raw: {json.dumps(res_json, indent=2)[:500]}")
            print(f"======================\n")

            # OpenAI-compatible format
            content = res_json["choices"][0]["message"]["content"]
            return content

    except urllib.error.HTTPError as he:
        err_body = ""
        try:
            err_body = he.read().decode("utf-8")
        except Exception:
            pass
        print(f"[LLM System] API failed with HTTP {he.code}: {he.reason}")
        if err_body:
            print(f"  Error body: {err_body[:300]}")
    except Exception as e:
        print(f"[LLM System] API request failed: {e}")

    return None


# ── Heuristic Mock Fallback ───────────────────────────────────────────────────

def _heuristic_response(player_text: str) -> dict:
    """
    Premium rule-based mock fallback for offline / sandbox mode.
    Provides reasonable responses when no LLM is available.
    """
    text_lower = player_text.lower()

    # Special handling for Saif's defiance/disobedience excuse
    if "refuse" in text_lower or "defiance" in text_lower or "excuse" in text_lower or "disobey" in text_lower:
        if "heal" in text_lower or "potion" in text_lower:
            dialogue = "I need to stay on my feet to finish this. The potion was necessary."
        else:
            dialogue = "Covering my flank makes more sense than a blind charge right now."
        return {
            "dialogue": f"[Offline] {dialogue}",
            "respect_change": 0
        }

    positive_words = [
        "leader", "trust", "stay", "protect", "help", "friend",
        "believe", "save", "together", "honor", "brave", "fight",
        "strong", "respect", "ally", "defend", "courage"
    ]
    negative_words = [
        "coward", "weak", "blame", "run", "fail", "bad",
        "useless", "scared", "pathetic", "fool", "stupid",
        "worthless", "quit", "give up", "abandon"
    ]

    pos_score = sum(1 for w in positive_words if w in text_lower)
    neg_score = sum(1 for w in negative_words if w in text_lower)

    if pos_score > neg_score:
        dialogue = "I want to support you, but I have seen too many battles. Perhaps your words have truth."
        respect_change = 10
    elif neg_score > pos_score:
        dialogue = "Do you think I do not know my own failures? Your accusations cut deep!"
        respect_change = -10
    else:
        dialogue = "This path offers no easy answers. We must watch our step."
        respect_change = 0

    return {
        "dialogue": f"[Offline] {dialogue}",
        "respect_change": respect_change
    }


# ── Main Entry Point ─────────────────────────────────────────────────────────

def generate_llm_response(player_text: str, game_state: dict) -> dict:
    """
    Unified LLM query function. Routes to the configured provider, extracts
    and validates the response, and guarantees a clean dict is returned.

    The game loop NEVER receives None or malformed data from this function.

    Args:
        player_text: The player's typed input.
        game_state: Dict containing game stats and LLM configuration.

    Returns:
        dict with exactly {"dialogue": str, "respect_change": int}
    """
    # ── Resolve configuration (env var → game_state → default) ────────────
    provider = (
        os.environ.get("LLM_PROVIDER")
        or game_state.get("llm_provider", "ollama")
    )
    ollama_model = (
        os.environ.get("OLLAMA_MODEL")
        or game_state.get("ollama_model", "gemma4:e4b")
    )
    ollama_url = (
        os.environ.get("OLLAMA_URL")
        or game_state.get("ollama_url", "http://localhost:11434")
    )
    api_base_url = (
        os.environ.get("API_BASE_URL")
        or game_state.get("api_base_url",
                          "https://generativelanguage.googleapis.com/v1beta/openai")
    )
    api_model = (
        os.environ.get("API_MODEL")
        or game_state.get("api_model", "gemini-2.5-flash")
    )
    api_key = os.environ.get("API_KEY", "")

    # Think toggle: env var → game_state → default True
    think_env = os.environ.get("LLM_THINK")
    if think_env is not None:
        think = think_env.lower() in ("true", "1", "yes")
    else:
        think = game_state.get("llm_think", True)

    # ── Extract game stats ────────────────────────────────────────────────
    saif_respect = game_state.get("saif_respect", 50)
    player_hp = game_state.get("player_hp", 100)
    enemy_hp = game_state.get("enemy_hp", 100)
    chat_history = game_state.get("chat_history", [])
    in_combat = game_state.get("in_combat", True)
    current_location = game_state.get("current_location", "overworld")

    # ── Build prompts ─────────────────────────────────────────────────────
    global_flags = game_state.get("global_flags", {})
    world_context = _build_world_context(global_flags)
    system_prompt = _build_system_prompt(saif_respect, player_hp, enemy_hp, in_combat, current_location)
    system_prompt = world_context + "\n\n" + system_prompt
    user_prompt = _build_user_prompt(player_text, chat_history)

    # ── Provider dispatch ─────────────────────────────────────────────────
    raw_text = None

    if provider == "ollama":
        raw_text = _call_ollama(
            system_prompt, user_prompt,
            model=ollama_model,
            base_url=ollama_url,
            think=think
        )
    elif provider == "api":
        if not api_key:
            print("[LLM System] No API key found. Set API_KEY env var or configure in Settings.")
            print("  Falling back to heuristic response.")
        else:
            raw_text = _call_api(
                system_prompt, user_prompt,
                model=api_model,
                base_url=api_base_url,
                api_key=api_key
            )
    else:
        print(f"[LLM System] Unknown provider '{provider}'. Falling back to heuristic.")

    # ── Extract and validate ──────────────────────────────────────────────
    if raw_text:
        result = extract_json_payload(raw_text)
        print(f"[LLM Result] dialogue='{result['dialogue'][:60]}...' "
              f"respect_change={result['respect_change']}")
        return result

    # ── Fallback: heuristic mock ──────────────────────────────────────────
    print("[LLM System] All providers failed. Using heuristic fallback.")
    return _heuristic_response(player_text)


def fetch_refusal_dialogue(game_state: dict, recent_chat: list = None) -> list:
    """
    Queries the configured LLM provider to fetch a JSON list of 2 combat excuses.
    Returns a list of strings on success, or an offline fallback list on failure.
    """
    provider = game_state.get("llm_provider", "ollama")
    ollama_model = game_state.get("ollama_model", "gemma4:e4b")
    ollama_url = game_state.get("ollama_url", "http://localhost:11434")
    api_base_url = game_state.get("api_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    api_model = game_state.get("api_model", "gemini-2.5-flash")
    api_key = os.environ.get("API_KEY", "")
    saif_respect = game_state.get("saif_respect", 50)
    
    if recent_chat is None:
        recent_chat = game_state.get("chat_history", [])[-3:]
    
    # Format chat history
    history_str = ""
    if recent_chat:
        for exchange in recent_chat:
            if len(exchange) == 2:
                history_str += f'Player: "{exchange[0]}"\nSaif: "{exchange[1]}"\n'
        history_str = history_str.strip()

    global_flags = game_state.get("global_flags", {})
    world_context = _build_world_context(global_flags)

    system_prompt = (
        "You are Saif (or the active party member), a weary, pragmatic, and tactical warrior. Speak conversationally and directly. "
        "NEVER use poetic metaphors about the desert, sand, or the sun. Do not be overly dramatic. Use modern, grounded syntax. "
        f"Your respect for the player is currently {saif_respect}/100. "
        "Generate a JSON array of 2 short combat excuses for refusing an order. "
        f"Consider this recent chat history: [{history_str}]. "
        "If the player was mean, hold a grudge. If they were kind, be pragmatic. "
        "You MUST directly reference or incorporate details from the recent conversation history in your refusal responses "
        "if it is relevant to your refusal or your relationship with the player (for instance, if the player has been "
        "insulting, threatening, nice, or supportive, let that directly inform the tone, attitude, and reasons in your excuses). "
        "Do NOT include thinking tags or other markdown formatting. Return ONLY the raw JSON array."
    )
    system_prompt = world_context + "\n\n" + system_prompt
    
    raw_text = None
    if provider == "ollama":
        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the JSON array of 2 excuses."}
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.7}
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                raw_text = res_json.get("message", {}).get("content", "")
        except Exception as e:
            print(f"[LLM Buffer] Ollama fetch failed: {e}")
    elif provider == "api":
        if not api_key:
            print("[LLM Buffer] API key not configured.")
        else:
            url = f"{api_base_url.rstrip('/')}/v1/chat/completions"
            payload = {
                "model": api_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Generate the JSON array of 2 excuses."}
                ],
                "temperature": 0.7,
                "response_format": {"type": "json_object"}
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as response:
                    res_body = response.read().decode("utf-8")
                    res_json = json.loads(res_body)
                    raw_text = res_json["choices"][0]["message"]["content"]
            except Exception as e:
                print(f"[LLM Buffer] API fetch failed: {e}")
                
    if raw_text:
        try:
            cleaned = _strip_think_blocks(raw_text)
            cleaned = _strip_markdown_fences(cleaned)
            match = re.search(r"(\[.*\])", cleaned, re.DOTALL)
            if match:
                array_str = match.group(1)
                parsed = json.loads(array_str)
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    return parsed
        except Exception as e:
            print(f"[LLM Buffer] JSON parsing of excuses failed: {e}. Raw content: {raw_text}")
            
    return [
        "Covering my flank makes more sense right now.",
        "Watch your own back."
    ]


def prewarm_llm(game_state: dict) -> bool:
    """
    Makes a lightweight, asynchronous handshake call to load the model into memory/VRAM.
    Returns True if completed (success or failure).
    """
    provider = game_state.get("llm_provider", "ollama")
    ollama_model = game_state.get("ollama_model", "gemma4:e4b")
    ollama_url = game_state.get("ollama_url", "http://localhost:11434")
    api_base_url = game_state.get("api_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    api_model = game_state.get("api_model", "gemini-2.5-flash")
    api_key = os.environ.get("API_KEY", "")
    
    system_prompt = "You are a game engine handshake agent. Respond with only 'OK' and nothing else."
    
    if provider == "ollama":
        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Hello"}
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 5}
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            # Increased timeout to 60s for cold model loading
            with urllib.request.urlopen(req, timeout=60) as response:
                response.read()
                print("[LLM Prewarm] Ollama pre-warming complete.")
                return True
        except Exception as e:
            print(f"[LLM Prewarm] Ollama pre-warming handshake failed/skipped: {e}")
            return False
    elif provider == "api":
        if not api_key:
            print("[LLM Prewarm] API key not configured. Skipping prewarm.")
            return False
        url = f"{api_base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": api_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Hello"}
            ],
            "max_tokens": 5,
            "temperature": 0.1
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                },
                method="POST"
            )
            # Increased timeout to 60s for cold model loading
            with urllib.request.urlopen(req, timeout=60) as response:
                response.read()
                print("[LLM Prewarm] API pre-warming complete.")
                return True
        except Exception as e:
            print(f"[LLM Prewarm] API pre-warming handshake failed/skipped: {e}")
            return False
    return False


def wake_up_llm(player_level: int = 1, config: dict = None) -> str:
    """
    Sends a tiny prompt to warm up the LLM and verify it's awake:
    'The player is at level [player_level] and just booted the game. Give a 5-word greeting.'
    Prints the response to the terminal.
    """
    if config is None:
        state_file = os.path.join("data", "game_state.json")
        config = {}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as f:
                    config = json.load(f)
            except Exception:
                pass
                
    provider = config.get("llm_provider", "ollama")
    ollama_model = config.get("ollama_model", "gemma4:e4b")
    ollama_url = config.get("ollama_url", "http://localhost:11434")
    api_base_url = config.get("api_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    api_model = config.get("api_model", "gemini-2.5-flash")
    api_key = os.environ.get("API_KEY", "")
    
    prompt = f"The player is at level {player_level} and just booted the game. Give a 5-word greeting."
    
    raw_text = None
    if provider == "ollama":
        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 15}
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            # Increased timeout to 60s for cold model loading
            with urllib.request.urlopen(req, timeout=60) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                raw_text = res_json.get("message", {}).get("content", "").strip()
        except Exception as e:
            raw_text = f"Ollama wakeup failed: {e}"
    elif provider == "api":
        if not api_key:
            raw_text = "API key not configured."
        else:
            url = f"{api_base_url.rstrip('/')}/v1/chat/completions"
            payload = {
                "model": api_model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 15,
                "temperature": 0.7
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}"
                    },
                    method="POST"
                )
                # Increased timeout to 60s for cold model loading
                with urllib.request.urlopen(req, timeout=60) as response:
                    res_body = response.read().decode("utf-8")
                    res_json = json.loads(res_body)
                    raw_text = res_json["choices"][0]["message"]["content"].strip()
            except Exception as e:
                raw_text = f"API wakeup failed: {e}"
                
    if raw_text:
        print(f"[LLM Wakeup] Handshake response: {raw_text}")
        return raw_text
    return "Handshake failed."


