from enum import Enum

class GameState(Enum):
    TOWN = "TOWN"
    OVERWORLD = "OVERWORLD"
    DUNGEON = "DUNGEON"
    COMBAT = "COMBAT"
    CAMP = "CAMP"

class GameStateManager:
    """
    Centralized State Engine for managing the RPG gameplay loop:
    Town -> Overworld -> Dungeon -> Combat / Camp.
    Controls which map render/update layer is active.
    """
    def __init__(self, initial_state: GameState = GameState.TOWN):
        self._current_state = initial_state
        print(f"[GameStateManager] Initialized in state: {self._current_state.name}")

    @property
    def current_state(self) -> GameState:
        return self._current_state

    def set_state(self, new_state: GameState):
        """
        Transitions to a new state and outputs a clean console log flag.
        """
        if not isinstance(new_state, GameState):
            raise ValueError(f"Invalid state target: {new_state}")
        
        old_state = self._current_state
        if old_state != new_state:
            self._current_state = new_state
            # Required console log format
            print(f"[Engine] Transitioning from {old_state.name} to {new_state.name}")
