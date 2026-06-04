import os
import json

class InventoryManager:
    """
    InventoryManager tracks player loot and items database.
    Updates the inventory dictionary in game_state.json and in-memory game instance.
    """
    def __init__(self, data_manager, game_instance=None):
        self.data_manager = data_manager
        self.game_instance = game_instance
        self.items = {}
        self.load_items()

    def load_items(self):
        """Loads items database if available from data_manager."""
        if hasattr(self.data_manager, "items") and self.data_manager.items:
            self.items = self.data_manager.items
        else:
            items_path = os.path.join(self.data_manager.data_dir, "items.json")
            if os.path.exists(items_path):
                try:
                    with open(items_path, "r", encoding="utf-8") as f:
                        self.items = json.load(f)
                except Exception as e:
                    print(f"[Warning] Failed to load items database directly: {e}")

    def add_item(self, item_id: str, quantity: int = 1) -> None:
        """
        Adds specified quantity of item to player inventory ledger.
        Saves updated inventory to game_state.json.
        """
        if self.game_instance is not None:
            if not isinstance(self.game_instance.inventory, dict):
                self.game_instance.inventory = {}
            self.game_instance.inventory[item_id] = self.game_instance.inventory.get(item_id, 0) + quantity
            if self.game_instance.inventory[item_id] <= 0:
                del self.game_instance.inventory[item_id]
            self.game_instance._save_game_state()
        else:
            # Fallback direct file modification if no active game instance
            state_file = "data/game_state.json"
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r") as f:
                        data = json.load(f)
                    
                    if "inventory" not in data or not isinstance(data["inventory"], dict):
                        data["inventory"] = {}
                    data["inventory"][item_id] = data["inventory"].get(item_id, 0) + quantity
                    if data["inventory"][item_id] <= 0:
                        del data["inventory"][item_id]
                    
                    with open(state_file, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception as e:
                    print(f"[Warning] Direct inventory save failed: {e}")

    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        """
        Removes specified quantity of item from player inventory ledger.
        Returns True if successful, or False if insufficient quantity.
        """
        if self.game_instance is not None:
            if not isinstance(self.game_instance.inventory, dict):
                self.game_instance.inventory = {}
            current_qty = self.game_instance.inventory.get(item_id, 0)
            if current_qty < quantity:
                return False
            self.game_instance.inventory[item_id] = current_qty - quantity
            if self.game_instance.inventory[item_id] <= 0:
                del self.game_instance.inventory[item_id]
            self.game_instance._save_game_state()
            return True
        else:
            # Fallback direct file modification if no active game instance
            state_file = "data/game_state.json"
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r") as f:
                        data = json.load(f)
                    
                    if "inventory" not in data or not isinstance(data["inventory"], dict):
                        data["inventory"] = {}
                    current_qty = data["inventory"].get(item_id, 0)
                    if current_qty < quantity:
                        return False
                    data["inventory"][item_id] = current_qty - quantity
                    if data["inventory"][item_id] <= 0:
                        del data["inventory"][item_id]
                    
                    with open(state_file, "w") as f:
                        json.dump(data, f, indent=2)
                    return True
                except Exception as e:
                    print(f"[Warning] Direct inventory save failed: {e}")
            return False
