import os
import json

class QuestManager:
    """
    QuestManager tracks Narrative flags, World state progression, and Quests.
    Loads quests.json via DataManager. Updates global_flags in game_state.json.
    """
    def __init__(self, data_manager, game_instance=None):
        self.data_manager = data_manager
        self.game_instance = game_instance
        self.quests = {}
        self.load_quests()

    def load_quests(self):
        """Loads quests database if available from data_manager."""
        if hasattr(self.data_manager, "quests") and self.data_manager.quests:
            self.quests = self.data_manager.quests
        else:
            # Fallback to direct file read if not registered in DataManager
            quests_path = os.path.join(self.data_manager.data_dir, "quests.json")
            if os.path.exists(quests_path):
                try:
                    with open(quests_path, "r", encoding="utf-8") as f:
                        self.quests = json.load(f)
                except Exception as e:
                    print(f"[Warning] Failed to load quests database directly: {e}")

    def set_flag(self, flag_name: str, value) -> None:
        """
        Sets a global narrative/quest flag.
        Updates the in-memory state of the active game instance and persists it to game_state.json.
        """
        # If we have an active game instance, update its in-memory flags
        if self.game_instance is not None:
            self.game_instance.global_flags[flag_name] = value
            self.game_instance._save_game_state()
            
            # Check if this flag triggers or completes any quests
            self.check_quest_triggers()
        else:
            # Fallback direct file modification if no active game instance is running
            state_file = "data/game_state.json"
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r") as f:
                        data = json.load(f)
                    
                    if "global_flags" not in data:
                        data["global_flags"] = {}
                    data["global_flags"][flag_name] = value
                    
                    with open(state_file, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception as e:
                    print(f"[Warning] Direct flag save failed: {e}")

    def check_flag(self, flag_name: str):
        """Checks the value of a global flag. Returns None or default if not set."""
        if self.game_instance is not None:
            return self.game_instance.global_flags.get(flag_name, None)
        else:
            state_file = "data/game_state.json"
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r") as f:
                        data = json.load(f)
                    return data.get("global_flags", {}).get(flag_name, None)
                except Exception:
                    pass
        return None

    def check_quest_triggers(self):
        """
        Analyzes active flags and awards quest completion rewards (e.g. EXP).
        Can be expanded for full narrative quest logging.
        """
        if not self.game_instance:
            return
            
        for quest_id, quest_info in self.quests.items():
            trigger = quest_info.get("trigger_flag")
            completion = quest_info.get("completion_flag")
            reward_exp = quest_info.get("reward_exp", 0)
            
            # If the trigger flag is active, and completion flag is active
            # and the quest hasn't been rewarded yet (we can store completion reward status as a flag)
            reward_flag = f"quest_{quest_id}_rewarded"
            if self.check_flag(trigger) and self.check_flag(completion):
                if not self.check_flag(reward_flag):
                    print(f"[Quest Complete] {quest_info['name']}! Awarding {reward_exp} EXP.")
                    self.game_instance.player_exp += reward_exp
                    
                    # Spawn floating quest complete +EXP text at the player position
                    self.game_instance.floating_texts.append({
                        "text": f"+{reward_exp} EXP (Quest)",
                        "x": self.game_instance.player_combat_pos[0] + self.game_instance.player.size // 2,
                        "y": self.game_instance.player_combat_pos[1] - 40,
                        "timer": 120
                    })
                    
                    # Level up check
                    self.game_instance.levelled_up = False
                    while self.game_instance.player_exp >= self.game_instance.exp_to_next_level:
                        self.game_instance.player_exp -= self.game_instance.exp_to_next_level
                        self.game_instance.player_level += 1
                        self.game_instance.exp_to_next_level = int(self.game_instance.exp_to_next_level * 1.5)
                        self.game_instance.player_max_hp += 10
                        self.game_instance.player_base_damage += 10
                        self.game_instance.player_hp = self.game_instance.player_max_hp
                        self.game_instance.levelled_up = True
                        
                    if self.game_instance.levelled_up:
                        print(f"[System] Level Up! Player is now Level {self.game_instance.player_level}.")
                        self.game_instance.screen_shake_frames = 30
                        self.game_instance.floating_texts.append({
                            "text": "LEVEL UP!",
                            "x": self.game_instance.player_combat_pos[0] + self.game_instance.player.size // 2,
                            "y": self.game_instance.player_combat_pos[1] - 80,
                            "timer": 120
                        })
                        
                    # Mark quest rewarded
                    self.game_instance.global_flags[reward_flag] = True
                    self.game_instance._save_game_state()
