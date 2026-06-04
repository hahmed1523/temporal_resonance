import os
import json

class DataManager:
    """
    DataManager handles loading, caching, and retrieving data-driven game assets
    from JSON databases. Runs once at game startup to prevent disk-read lags.
    """
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.enemies = {}
        self.maps = {}
        self.load_all_data()

    def load_all_data(self):
        """Loads all JSON files into memory dictionaries."""
        enemies_path = os.path.join(self.data_dir, "enemies.json")
        maps_path = os.path.join(self.data_dir, "maps.json")

        # Load Enemies Database
        if os.path.exists(enemies_path):
            try:
                with open(enemies_path, "r", encoding="utf-8") as f:
                    self.enemies = json.load(f)
                print(f"[DataManager] Loaded {len(self.enemies)} enemies successfully.")
            except Exception as e:
                print(f"[Warning] Failed to load enemies database: {e}")
        else:
            print(f"[Warning] Enemies database not found at {enemies_path}")

        # Load Maps Database
        if os.path.exists(maps_path):
            try:
                with open(maps_path, "r", encoding="utf-8") as f:
                    self.maps = json.load(f)
                print(f"[DataManager] Loaded {len(self.maps)} maps successfully.")
            except Exception as e:
                print(f"[Warning] Failed to load maps database: {e}")
        else:
            print(f"[Warning] Maps database not found at {maps_path}")

    def get_enemy_data(self, enemy_id: str) -> dict:
        """
        Retrieves data for a specific enemy ID.
        Returns a default dict structure if the enemy ID is not found.
        """
        if enemy_id in self.enemies:
            return self.enemies[enemy_id]
        
        print(f"[Warning] Enemy ID '{enemy_id}' not found in Bestiary. Using default goblin_grunt stats.")
        # Fallback default stats
        return {
            "name": "Unknown Grunt",
            "max_hp": 30,
            "base_damage": 5,
            "exp_yield": 20,
            "color": [0, 255, 0],
            "size": 40
        }

    def get_map_data(self, map_id: str) -> dict:
        """
        Retrieves layout and spawning data for a specific map ID.
        Returns None if the map ID is not found.
        """
        if map_id in self.maps:
            return self.maps[map_id]
        
        print(f"[Error] Map ID '{map_id}' not found in Atlas.")
        return None
