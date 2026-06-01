#!/usr/bin/env python3
"""
Temporal Resonance
A top-down Chrono Trigger-style 2D RPG engine prototype.
"""

import sys
from engine.game import Game
from engine.level_maps import DEFAULT_MAP_GRID

def main():
    """
    Main entry point for starting the game prototype.
    """
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
