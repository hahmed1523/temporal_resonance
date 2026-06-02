#!/usr/bin/env python3
"""
Temporal Resonance
A top-down Chrono Trigger-style 2D RPG engine prototype.
"""

import sys
import json
import os

# Configure SDL to use PulseAudio on WSL2/WSLg for Windows audio passthrough.
# This must be set BEFORE pygame is imported.
os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")

import pygame

from engine.game import Game
from engine.level_maps import DEFAULT_MAP_GRID


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
        "enemy_hp": 100,
        "saif_respect": 50,
        "saif_hp": 100,
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
        "current_location": "overworld"
    }
    with open(state_file, "w") as f:
        json.dump(default_state, f, indent=2)
    print("[System] game_state.json reset to default starting values (config preserved).")

def main():
    """
    Main entry point for starting the game prototype.
    """
    # Initialize Pygame and the Mixer
    pygame.init()
    try:
        pygame.mixer.init()
        print("[System] Pygame mixer initialized successfully.")
    except Exception as e:
        print(f"[Warning] Failed to initialize pygame mixer: {e}. Running in silent mode.")

    # Create the game manager instance using our level map grid
    game = Game(
        width=800,
        height=600,
        title="Temporal Resonance - Core Engine Prototype",
        map_grid=DEFAULT_MAP_GRID
    )
    
    # Start the core game loop
    game.run()

if __name__ == "__main__":
    main()

