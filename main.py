#!/usr/bin/env python3
"""
Temporal Resonance
A top-down Chrono Trigger-style 2D RPG engine prototype.
"""

import sys
import json
import os

import pygame


from engine.game import Game
from engine.data_manager import DataManager


def reset_game_state():
    """
    Overwrites the game_state.json file with our default starting values
    to prevent persistence of HP, Respect, and chat history between sessions,
    while preserving custom LLM configuration keys if they already exist.
    """
    state_dir = "data"
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, "game_state.json")
    
    # Configuration defaults
    llm_provider = "ollama"
    ollama_model = "gemma4:e4b"
    ollama_url = "http://localhost:11434"
    api_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    api_model = "gemini-2.5-flash"
    llm_think = True
    
    # Try to load existing configuration keys
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                existing_data = json.load(f)
                llm_provider = existing_data.get("llm_provider", llm_provider)
                ollama_model = existing_data.get("ollama_model", ollama_model)
                ollama_url = existing_data.get("ollama_url", ollama_url)
                api_base_url = existing_data.get("api_base_url", api_base_url)
                api_model = existing_data.get("api_model", api_model)
                llm_think = existing_data.get("llm_think", llm_think)
        except Exception:
            pass  # Fall back to defaults if file is corrupted
            
    default_state = {
        "player_hp": 100,
        "player_max_hp": 100,
        "player_level": 1,
        "player_exp": 0,
        "exp_to_next_level": 100,
        "player_base_damage": 20,
        "enemy_hp": 100,
        "saif_respect": 50,
        "saif_hp": 100,
        "saif_max_hp": 100,
        "saif_level": 1,
        "saif_exp": 0,
        "saif_exp_to_next_level": 100,
        "saif_base_damage": 15,
        "chest_opened": False,
        "saif_recruited": False,
        "chat_history": [],
        "llm_provider": llm_provider,
        "ollama_model": ollama_model,
        "ollama_url": ollama_url,
        "api_base_url": api_base_url,
        "api_model": api_model,
        "llm_think": llm_think,
        "inventory": {"health_potion": 0},
        "saif_refusal_queue": [],
        "current_location": "overworld"
    }
    with open(state_file, "w") as f:
        json.dump(default_state, f, indent=2)
    print("[System] game_state.json reset to default starting values (config preserved).")

def main():
    """
    Main entry point for starting the game prototype.
    """
    # Pre-initialize pygame mixer with 44.1kHz stereo and a larger 4096-byte buffer
    # to prevent buffer underruns and scratchy/crackling audio playback.
    try:
        pygame.mixer.pre_init(44100, -16, 2, 4096)
    except Exception as e:
        print(f"[Warning] Failed to pre-initialize pygame mixer: {e}")

    # Initialize Pygame and the Mixer
    pygame.init()
    try:
        pygame.mixer.init()
        print("[System] Pygame mixer initialized successfully.")
    except Exception as e:
        print(f"[Warning] Failed to initialize pygame mixer: {e}. Running in silent mode.")

    # Create the DataManager instance to load database configurations
    data_manager = DataManager()

    # Create the game manager instance
    game = Game(
        width=800,
        height=600,
        title="Temporal Resonance - Core Engine Prototype",
        data_manager=data_manager
    )
    
    # Fire off LLM wakeup handshake in background (MainMenu state initialization)
    try:
        import threading
        from engine.llm_handler import wake_up_llm
        player_level = 1
        state_file = os.path.join("data", "game_state.json")
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                state_data = json.load(f)
                player_level = state_data.get("player_level", 1)
        
        t = threading.Thread(target=wake_up_llm, args=(player_level,))
        t.daemon = True
        t.start()
    except Exception as e:
        print(f"[Warning] Failed to start LLM wakeup thread: {e}")
    
    # Start the core game loop
    game.run()

if __name__ == "__main__":
    main()

