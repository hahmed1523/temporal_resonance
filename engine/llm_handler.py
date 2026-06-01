import urllib.request
import urllib.error
import json
import os
import random
import re

def scrub_json_response(raw_text: str) -> dict:
    """
    Sanitizes raw model output to find and extract the valid JSON object segment,
    removing any conversational padding, introductory text, or <think> tags.
    """
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception as e:
            print(f"[LLM Scrubber] JSON decoding failed on parsed segment: {e}")
            print(f"Parsed Segment: {match.group()}")
    else:
        print("[LLM Scrubber] No JSON block matched in model response.")
        print(f"Raw response was: {raw_text}")
    return None

def generate_llm_response(player_text: str, game_state: dict) -> dict:
    """
    Queries selected LLM provider (standard Gemini API or model-agnostic local Ollama),
    with a robust rule-based mock fallback.
    Injects dynamic game state variables (HP, Respect) and rolling chat history context.
    Returns: dict {"dialogue": str, "respect_change": int}
    """
    # Extract stats from game_state
    saif_respect = game_state.get("saif_respect", 50)
    player_hp = game_state.get("player_hp", 100)
    enemy_hp = game_state.get("enemy_hp", 100)
    chat_history = game_state.get("chat_history", [])
    
    # Resolve LLM configuration options (prioritizing environment variables)
    llm_provider = os.environ.get("LLM_PROVIDER") or game_state.get("llm_provider", "gemini")
    ollama_model = os.environ.get("OLLAMA_MODEL") or game_state.get("ollama_model", "gemma4:e4b")
    ollama_url = os.environ.get("OLLAMA_URL") or game_state.get("ollama_url", "http://localhost:11434")
    
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
    if llm_provider == "gemini" and api_key:
        model_name = "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        in_combat = game_state.get("in_combat", True)
        if in_combat:
            system_instruction = (
                f"You are Saif, an Arabian Desert Guardian. You are currently in battle. "
                f"Your Respect for the player is {saif_respect}/100. "
                f"The Player has {player_hp} HP. The Enemy has {enemy_hp} HP. "
                f"Factor these stats into your response. "
                f"Respond in 1 or 2 short sentences. Based on what they say, decide if "
                f"your respect for them goes up (+10), down (-10), or stays the same (0)."
            )
        else:
            system_instruction = (
                f"You are Saif, an Arabian Desert Guardian. A stranger has approached you on the map. "
                f"You are cautious but can be convinced to join them. "
                f"Your Respect for them is {saif_respect}/100. "
                f"Factor this stat into your response. "
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
                scrubbed = scrub_json_response(text_out)
                if scrubbed:
                    return scrubbed
        except urllib.error.HTTPError as he:
            err_body = he.read().decode('utf-8') if he else "No error body"
            print(f"[LLM System] Gemini API failed with HTTP {he.code}: {he.reason}")
            print(f"Error Response Body:\n{err_body}")
        except Exception as e:
            print(f"[LLM System] Gemini API failed: {e}. Falling back...")
            
    # 2. Model-Agnostic Native Ollama Chat Endpoint
    if llm_provider == "ollama" or (llm_provider == "gemini" and not api_key):
        url = f"{ollama_url.rstrip('/')}/api/chat"
        in_combat = game_state.get("in_combat", True)
        
        if in_combat:
            system_prompt = (
                f"You are Saif, an Arabian Desert Guardian in battle. "
                f"Your Respect for the player is {saif_respect}/100. "
                f"The Player has {player_hp} HP. The Enemy has {enemy_hp} HP. "
                f"Factor these stats into your response. "
                f"Respond in 1 or 2 short sentences. "
                f"Based on what they say, you MUST adjust your respect level: "
                f"increase by +10 if they speak bravely, respectfully, or offer genuine help; "
                f"decrease by -10 if they act weak, complain, insult you, or act cowardly; "
                f"otherwise return 0."
            )
        else:
            system_prompt = (
                f"You are Saif, an Arabian Desert Guardian cautious about a stranger who approached you on the map. "
                f"Your Respect for them is {saif_respect}/100. "
                f"Factor this stat into your response. "
                f"Respond in 1 or 2 short sentences. "
                f"Based on what they say, you MUST adjust your respect level: "
                f"increase by +10 if they speak respectfully, bravely, or appeal to your honor/duty; "
                f"decrease by -10 if they act weak, complain, insult you, or act cowardly; "
                f"otherwise return 0."
            )
            
        user_prompt = (
            f"{history_str}"
            f"Player says: \"{player_text}\"\n\n"
            f"Return a JSON object matching this schema: "
            f"{{\"dialogue\": \"Saif's reply\", \"respect_change\": integer (-10, 0, or 10)}}. "
            f"IMPORTANT: If your internal thinking process decides to change respect (e.g. +10 or -10), "
            f"you MUST reflect this identical integer value (+10, -10, or 0) in the 'respect_change' "
            f"field of your final JSON response block. Do not output 0 if you reasoned it should change!"
        )
        
        payload = {
            "model": ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "format": "json",
            "think": False,
            "stream": False,
            "options": {
                "temperature": 0.5
            }
        }
        
        print("\n=== [Ollama API Request] ===")
        print(f"Target URL: {url}")
        print(f"Model: {ollama_model}")
        print(f"Payload Sent:\n{json.dumps(payload, indent=2)}")
        print("============================\n")
        
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                
                print("=== [Ollama API Response] ===")
                print(f"Raw Response:\n{json.dumps(res_json, indent=2)}")
                print("=============================\n")
                
                text_out = res_json['message']['content']
                scrubbed = scrub_json_response(text_out)
                if scrubbed:
                    return scrubbed
        except Exception as e:
            print(f"[LLM System] Ollama native API query failed: {e}. Trying legacy local compatibility...")

    # 3. Legacy Local LLM compatible fallback
    local_url = os.environ.get("LOCAL_LLM_URL")
    if local_url or os.environ.get("USE_LOCAL_LLM"):
        url = local_url or "http://localhost:11434/v1/chat/completions"
        in_combat = game_state.get("in_combat", True)
        if in_combat:
            system_prompt = (
                f"You are Saif, an Arabian Desert Guardian. You are currently in battle. "
                f"Your Respect for the player is {saif_respect}/100. "
                f"The Player has {player_hp} HP. The Enemy has {enemy_hp} HP. "
                f"Factor these stats into your response. "
                f"Respond in 1-2 short sentences. Decide if respect changes: +10, -10, or 0. "
                f"You must output ONLY a JSON object matching: {{\"dialogue\": \"reply\", \"respect_change\": integer}}"
            )
        else:
            system_prompt = (
                f"You are Saif, an Arabian Desert Guardian. A stranger has approached you on the map. "
                f"You are cautious but can be convinced to join them. "
                f"Your Respect for them is {saif_respect}/100. "
                f"Factor this stat into your response. "
                f"Respond in 1-2 short sentences. Decide if respect changes: +10, -10, or 0. "
                f"You must output ONLY a JSON object matching: {{\"dialogue\": \"reply\", \"respect_change\": integer}}"
            )
        user_content = f"{history_str}Player: '{player_text}'"
        payload = {
            "model": ollama_model,
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
            with urllib.request.urlopen(req, timeout=60) as response:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                text_out = res_json['choices'][0]['message']['content']
                scrubbed = scrub_json_response(text_out)
                if scrubbed:
                    return scrubbed
        except Exception as e:
            print(f"[LLM System] Legacy Local LLM failed: {e}. Falling back...")

    # 4. Premium Rule-Based Mock Fallback (Offline / Sandbox)
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
