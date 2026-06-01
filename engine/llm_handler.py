import urllib.request
import urllib.error
import json
import os
import random

def generate_llm_response(player_text: str, game_state: dict) -> dict:
    """
    Queries standard Gemini API or local Ollama server, with a robust rule-based mock fallback.
    Injects dynamic game state variables (HP, Respect) and rolling chat history context.
    Returns: dict {"dialogue": str, "respect_change": int}
    """
    # Extract stats from game_state
    saif_respect = game_state.get("saif_respect", 50)
    player_hp = game_state.get("player_hp", 100)
    enemy_hp = game_state.get("enemy_hp", 100)
    chat_history = game_state.get("chat_history", [])
    
    # Format rolling chat history
    history_str = ""
    if chat_history:
        history_str = "Recent Chat History:\n"
        for exchange in chat_history:
            if len(exchange) == 2:
                history_str += f"Player: \"{exchange[0]}\"\nSaif: \"{exchange[1]}\"\n"
        history_str += "\n"
        
    # 1. Check for standard Gemini API Key
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        model_name = "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        system_instruction = (
            f"You are Saif, an Arabian Desert Guardian. You are currently in battle. "
            f"Your Respect for the player is {saif_respect}/100. "
            f"The Player has {player_hp} HP. The Enemy has {enemy_hp} HP. "
            f"Factor these stats into your response. "
            f"Respond in 1 or 2 short sentences. Based on what they say, decide if "
            f"your respect for them goes up (+10), down (-10), or stays the same (0)."
        )
        
        prompt = (
            f"{history_str}"
            f"Player says: \"{player_text}\"\n\n"
            "Return a JSON object matching this schema: {\"dialogue\": \"Saif's reply\", \"respect_change\": integer (-10, 0, or 10)}"
        )
        
        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "dialogue": {"type": "STRING"},
                        "respect_change": {"type": "INTEGER"}
                    },
                    "required": ["dialogue", "respect_change"]
                }
            }
        }
        
        print("\n=== [LLM API Request] ===")
        print(f"Target URL: https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent")
        print(f"Payload Sent:\n{json.dumps(payload, indent=2)}")
        print("=========================\n")
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                
                print("=== [LLM API Response] ===")
                print(f"Raw Response:\n{json.dumps(res_json, indent=2)}")
                print("==========================\n")
                
                text_out = res_json['candidates'][0]['content']['parts'][0]['text']
                return json.loads(text_out)
        except urllib.error.HTTPError as he:
            err_body = he.read().decode('utf-8') if he else "No error body"
            print(f"[LLM System] Gemini API failed with HTTP {he.code}: {he.reason}")
            print(f"Error Response Body:\n{err_body}")
        except Exception as e:
            print(f"[LLM System] Gemini API failed: {e}. Falling back...")
            
    # 2. Check for local Ollama / local LLM endpoint
    local_url = os.environ.get("LOCAL_LLM_URL")
    if local_url or os.environ.get("USE_LOCAL_LLM"):
        url = local_url or "http://localhost:11434/v1/chat/completions"
        system_prompt = (
            f"You are Saif, an Arabian Desert Guardian. You are currently in battle. "
            f"Your Respect for the player is {saif_respect}/100. "
            f"The Player has {player_hp} HP. The Enemy has {enemy_hp} HP. "
            f"Factor these stats into your response. "
            f"Respond in 1-2 short sentences. Decide if respect changes: +10, -10, or 0. "
            f"You must output ONLY a JSON object matching: {{\"dialogue\": \"reply\", \"respect_change\": integer}}"
        )
        user_content = f"{history_str}Player: '{player_text}'"
        payload = {
            "model": "llama3",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"}
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                text_out = res_json['choices'][0]['message']['content']
                return json.loads(text_out)
        except Exception as e:
            print(f"[LLM System] Local LLM failed: {e}. Falling back...")

    # 3. Premium Rule-Based Mock Fallback (Offline / Sandbox)
    text_lower = player_text.lower()
    
    # Keyword analysis
    positive_words = ["leader", "trust", "stay", "protect", "help", "friend", "believe", "save", "together"]
    negative_words = ["coward", "weak", "blame", "run", "fail", "bad", "useless", "scared"]
    
    pos_score = sum(1 for w in positive_words if w in text_lower)
    neg_score = sum(1 for w in negative_words if w in text_lower)
    
    if pos_score > neg_score:
        dialogue = "I... I want to protect you, but the desert has taken so much. Perhaps your words have truth."
        respect_change = 10
    elif neg_score > pos_score:
        dialogue = "Do you think I do not know my own failures? Your accusations burn like the desert sun!"
        respect_change = -10
    else:
        dialogue = "The sands of time offer no easy answers. We must watch our step."
        respect_change = 0
        
    return {
        "dialogue": f"[Heuristic Saif] {dialogue}",
        "respect_change": respect_change
    }
