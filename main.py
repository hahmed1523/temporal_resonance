#!/usr/bin/env python3
"""
Temporal Resonance
A top-down Chrono Trigger-style 2D RPG engine prototype.
"""

import sys
import json
import os
from engine.game import Game
from engine.level_maps import DEFAULT_MAP_GRID

def reset_game_state():
    """
    Overwrites the game_state.json file with our default starting values
    to prevent persistence of HP, Respect, and chat history between sessions.
    """
    state_dir = "data"
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, "game_state.json")
    default_state = {
        "player_hp": 100,
        "enemy_hp": 100,
        "saif_respect": 50,
        "saif_hp": 100,
        "chest_opened": False,
        "chat_history": []
    }
    with open(state_file, "w") as f:
        json.dump(default_state, f, indent=2)
    print("[System] game_state.json reset to default starting values.")

def main():
    """
    Main entry point for starting the game prototype.
    """
    # Reset external state to defaults before starting the game
    reset_game_state()
    
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
