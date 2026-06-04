import pygame
import sys
import random
import json
import os
import math
import threading
from engine.player import Player
from engine.enemy import Enemy
from engine.chest import Chest
from engine.sound_manager import SoundManager
from engine.quest_manager import QuestManager

from engine.llm_handler import generate_llm_response, save_api_key_to_env, fetch_refusal_dialogue, prewarm_llm
from engine.level_maps import DEFAULT_MAP_GRID, TILE_SIZE, CAMP_MAP_GRID


class Game:
    """
    Main Game engine class.
    Manages the Pygame lifecycle, event handling, updating state, and rendering.
    """
    def __init__(self, width: int = 800, height: int = 600, title: str = "Temporal Resonance", data_manager=None):
        """
        Initializes Pygame, sets up the screen, game clock, and game entities.
        """
        try:
            pygame.mixer.pre_init(44100, -16, 2, 4096)
        except Exception as e:
            print(f"[Warning] Failed to pre-initialize pygame mixer in Game: {e}")
            
        pygame.init()
        try:
            pygame.mixer.init()
        except Exception as e:
            print(f"[Warning] Failed to initialize pygame mixer in Game: {e}")
            
        self.sound_manager = SoundManager()
        self.last_bgm_location = None

        
        # Screen dimensions and title
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(title)
        
        # Load level map grids from DataManager
        self.data_manager = data_manager
        overworld_data = self.data_manager.get_map_data("overworld") if self.data_manager else None
        camp_data = self.data_manager.get_map_data("camp") if self.data_manager else None
        
        if overworld_data:
            self.overworld_map_grid = [list(row) for row in overworld_data["grid"]]
        else:
            self.overworld_map_grid = DEFAULT_MAP_GRID
            
        if camp_data:
            self.camp_map_grid = [list(row) for row in camp_data["grid"]]
        else:
            self.camp_map_grid = CAMP_MAP_GRID
            
        self.map_grid = self.overworld_map_grid
        
        # Game loop control and clock
        self.clock = pygame.time.Clock()
        self.is_running = True
        
        # Aesthetics (sleek dark mode colors)
        self.bg_color = (24, 24, 28)       # Sleek deep charcoal background
        self.grid_color = (38, 38, 44)     # Subtle grid visual reference for grey-boxing
        self.panel_color = (32, 32, 38)    # Lighter charcoal for bottom panel
        
        # Font for Combat UI Text
        self.font = pygame.font.SysFont(None, 32)
        
        # JSON State Configuration
        self.state_file_path = os.path.join("data", "game_state.json")
        self.save_slot_file = "save_slot_1.json"
        
        # Initialize QuestManager
        self.quest_manager = QuestManager(self.data_manager, self)
        
        # Track overworld position & camera variables for camp pack-up
        self.overworld_player_x = 960
        self.overworld_player_y = 1040
        self.overworld_camera_x = 0.0
        self.overworld_camera_y = 0.0
        
        # Camp interactive entities and coordinates in 50x50 camp space
        self.campfire_pos = (960, 1040)
        self.saif_camp_pos = (880, 1040)
        self.elena_camp_pos = (1040, 1040)
        
        # Camp dialogue state
        self.active_camp_npc = None # 'saif' or 'elena'
        self.elena_dialogue_active = False
        
        # Initialize Game State
        self.state = 'main_menu_state'
        
        # Loader & Transition State Variables
        self.load_progress = 0.0
        self.load_target_state = 'exploration_state'
        self.prewarm_thread = None
        self.prewarm_complete = False
        self.prewarm_success = False
        self.transition_elapsed = 0.0
        self.spiral_coords = []
        self.transition_spiral_total = 0
        
        # Main Menu State Variables
        self.main_menu_index = 0
        self.main_menu_options = ["New Game", "Continue", "Settings", "Quit"]
        self.save_exists = os.path.exists(self.save_slot_file)
        if not self.save_exists:
            self.main_menu_index = 0  # Default to New Game if no save
        else:
            self.main_menu_index = 1  # Default to Continue if save exists
            
        # Pause Menu State Variables
        self.pause_menu_index = 0
        self.pause_menu_options = ["Resume", "Save Game", "Quit to Main Menu"]
        self.save_confirmed_time = 0
        self.no_save_message_time = 0
        
        # World map boundaries (grid is 50 rows × 50 cols, each tile is 40×40 px)
        self.tile_size = TILE_SIZE
        self.world_width = len(self.map_grid[0]) * self.tile_size
        self.world_height = len(self.map_grid) * self.tile_size
        
        # Camera Offset coordinates
        self.camera_x = 0.0
        self.camera_y = 0.0
        
        # Load Game State (which sets up self.enemy based on loaded flag settings)
        self._load_game_state()
        
        # Initialize Game Entities from maps.json / enemies.json
        overworld_data = self.data_manager.get_map_data("overworld") if self.data_manager else None
        
        player_x = 960
        player_y = 1040
        if overworld_data and "player_spawn" in overworld_data:
            player_x = overworld_data["player_spawn"][0] * self.tile_size
            player_y = overworld_data["player_spawn"][1] * self.tile_size
            
        self.player = Player(player_x, player_y)
        
        # Golden Chest — position derived from grid scan below
        self.chest = None
        
        # Scan grid to find Saif NPC tile 3
        self.saif_npc_x = None
        self.saif_npc_y = None
        for r_idx, row in enumerate(self.map_grid):
            for c_idx, cell in enumerate(row):
                if cell == 3:
                    self.saif_npc_x = c_idx * self.tile_size
                    self.saif_npc_y = r_idx * self.tile_size
                    break
            if self.saif_npc_x is not None:
                break
                    
        # Scan grid to find Chest tile 2 and create Chest entity at that position
        self.chest_x = None
        self.chest_y = None
        for r_idx, row in enumerate(self.map_grid):
            for c_idx, cell in enumerate(row):
                if cell == 2:
                    self.chest_x = c_idx * self.tile_size
                    self.chest_y = r_idx * self.tile_size
                    break
            if self.chest_x is not None:
                break
        if self.chest_x is not None:
            self.chest = Chest(self.chest_x, self.chest_y)
        
        # Trigger initial camera centering
        self._update_camera()
        
        # Combat Coordinates & Positions
        self.player_combat_pos = (150, 150)
        self.saif_combat_pos = (150, 230)
        self.enemy_combat_start_pos = (580, 190)
        self.enemy_combat_current_pos = list(self.enemy_combat_start_pos)
        self.is_sliding = False
        self.combat_ui_offset = 0.0
        self.is_combat_ending = False
        self.enemy_defeated_and_removed = False
        
        # Saif HP parameter & Enemy targeting variables
        self.saif_hp = 100
        self.enemy_target = 'player'
        
        self.combat_turn = 'player'  # 'player' or 'enemy'
        self.enemy_attack_active = False
        self.enemy_attack_start_time = 0
        self.parry_attempted = False
        self.parry_success = False
        
        # Dynamic Timing Variables (scaled when attack is triggered)
        self.forward_duration = 500
        self.total_duration = 1000
        self.parry_window_start = 420
        self.parry_window_end = 540
        
        # Combat Menu Navigation
        self.menu_options = ['Attack', 'Talk', 'Item', 'Flee']
        self.menu_index = 0
        
        # Talk Mode State Variables
        self.combat_mode = 'menu'  # 'menu', 'talk_input', 'talk_response'
        self.chat_input_text = ""
        self.talk_response_text = ""
        self.talk_response_start_time = 0
        
        # Camp Mode State Variables
        self.rest_notification_active = False
        
        # Settings Screen State Variables
        self.settings_field_index = 0  # Which setting is currently selected
        self.settings_fields = ['provider', 'model', 'api_key', 'think']
        self.settings_editing = False   # True when user is typing into a field
        self.settings_edit_buffer = ""  # Temp buffer for text input in settings
        self.settings_api_key_display = ""  # Masked display of API key

        # VFX State Variables
        self.screen_shake_frames = 0
        self.enemy_flash_frames = 0
        self.player_flash_frames = 0
        self.saif_flash_frames = 0
        self.player_recoil_frames = 0
        self.saif_recoil_frames = 0
        self.floating_texts = []

        # Combat Animation Variables
        self.player_combat_current_pos = list(self.player_combat_pos)
        self.saif_combat_current_pos = list(self.saif_combat_pos)
        self.player_attack_active = False
        self.player_attack_start_time = 0
        self.player_damage_dealt = False
        self.saif_attack_active = False
        self.saif_attack_start_time = 0
        self.saif_damage_dealt = False
        self.is_combo_attack = False
        self.combo_damage_applied = False
        self.enemy_damage_dealt = False
        self.combo_cooldown = 0
        self.saif_defending = False
        self.saif_excuse_active = False
        self.saif_excuse_text = ""
        self.saif_excuse_load_time = None
        self.saif_refusal_queue = []

    def _setup_enemy(self):
        """
        Sets up the overworld enemy based on map configurations.
        """
        overworld_data = self.data_manager.get_map_data("overworld") if self.data_manager else None
        enemy_x = 1120
        enemy_y = 1040
        enemy_color = (220, 20, 60)
        enemy_size = 40
        self.enemy_type = "desert_bandit"
        
        if overworld_data and overworld_data.get("enemy_spawns"):
            first_enemy = overworld_data["enemy_spawns"][0]
            self.enemy_type = first_enemy["type"]
            enemy_grid_pos = first_enemy["pos"]
            enemy_x = enemy_grid_pos[0] * self.tile_size
            enemy_y = enemy_grid_pos[1] * self.tile_size
            
            if self.data_manager:
                enemy_info = self.data_manager.get_enemy_data(self.enemy_type)
                enemy_color = tuple(enemy_info.get("color", [220, 20, 60]))
                enemy_size = enemy_info.get("size", 40)
                
        self.enemy = Enemy(enemy_x, enemy_y, size=enemy_size, color=enemy_color)

    def _adjust_respect(self, change: int):
        """
        Adjusts Saif's respect meter, keeping it within [0, 100].
        Triggers defection (leaves party forever) if respect hits 0.
        """
        self.saif_respect = max(0, min(100, self.saif_respect + change))
        if self.saif_recruited and self.saif_respect <= 0:
            print("[System] Saif's respect hit 0! He has abandoned your party forever.")
            self.saif_recruited = False
            self.saif_hp = 100
        elif self.saif_recruited and self.saif_respect <= 20:
            print("[System] WARNING: Saif's respect is critically low (<= 20)!")

    def _reset_combat_only_state(self):
        """
        Resets combat-specific variables only, preserving long-term relationship
        metrics like respect and recruitment status.
        """
        self.player_hp = self.player_max_hp
        self.enemy_hp = 100
        self.saif_hp = self.saif_max_hp
        self.combat_turn = 'player'
        self.combat_mode = 'menu'
        self.enemy_combat_current_pos = list(self.enemy_combat_start_pos)
        self.enemy_attack_active = False
        
        # Reset positions
        self.player_combat_current_pos = list(self.player_combat_pos)
        self.saif_combat_current_pos = list(self.saif_combat_pos)
        
        # Reset animation states
        self.player_attack_active = False
        self.saif_attack_active = False
        self.player_damage_dealt = False
        self.saif_damage_dealt = False
        self.is_combo_attack = False
        self.combo_damage_applied = False
        self.enemy_damage_dealt = False
        self.combo_cooldown = 0
        self.saif_defending = False
        self.saif_excuse_active = False
        self.saif_excuse_text = ""
        self.saif_excuse_load_time = None
        
        # Clear VFX state
        self.floating_texts = []
        self.screen_shake_frames = 0
        self.enemy_flash_frames = 0
        self.player_flash_frames = 0
        self.saif_flash_frames = 0
        self.player_recoil_frames = 0
        self.saif_recoil_frames = 0
        
        self.is_combat_ending = False
        self.enemy_defeated_and_removed = False
        self._save_game_state()

    def _start_enemy_turn(self):
        """
        Transitions to the enemy's attack turn with randomized timing and target.
        Consolidates the duplicated enemy-turn-setup logic used across combat actions.
        """
        self.combat_turn = 'enemy'
        self.enemy_attack_active = True
        self.enemy_attack_start_time = pygame.time.get_ticks()
        self.parry_attempted = False
        self.parry_success = False
        self.enemy_damage_dealt = False

        # Randomly pick target: 'player' or 'saif' (only if recruited)
        if self.saif_recruited:
            self.enemy_target = random.choice(['player', 'saif'])
        else:
            self.enemy_target = 'player'

        target_y = (self.player_combat_pos[1] if self.enemy_target == 'player'
                    else self.saif_combat_pos[1])
        self.enemy_combat_current_pos = [self.enemy_combat_start_pos[0], target_y]

        # Randomize forward attack lunge duration (300ms to 750ms)
        self.forward_duration = random.randint(300, 750)
        self.total_duration = self.forward_duration * 2

        # Scale parry window centered on impact
        self.parry_window_start = self.forward_duration - 100
        self.parry_window_end = self.forward_duration + 20

        print(f"[Debug System] Enemy targets: {self.enemy_target.upper()}. "
              f"Attack Speed Picked: {self.forward_duration}ms. "
              f"Parry range: {self.parry_window_start} - {self.parry_window_end}")

    def _end_current_turn(self):
        """
        Transitions turn from Player to Saif to Enemy based on recruitment status.
        If Saif is dead, his turn is skipped.
        """
        if self.combat_turn == 'player':
            if self.saif_recruited and self.saif_hp > 0:
                self.combat_turn = 'saif'
                self.menu_index = 0
                self.combat_mode = 'menu'
                self.menu_options = ['Attack', 'Special', 'Item', 'Flee']
                self.saif_defending = False
                print("[Combat] Saif's Turn!")
            else:
                self._start_enemy_turn()
        elif self.combat_turn == 'saif':
            self._start_enemy_turn()

    def _apply_damage_to_enemy(self, damage: int, is_combo: bool = False):
        """
        Applies damage to the enemy and triggers VFX (screen shake, white flash, floating texts).
        """
        self.sound_manager.play_sfx("hit")
        self.enemy_hp = max(0, self.enemy_hp - damage)
        self._save_game_state()


        target_x = int(self.enemy_combat_current_pos[0] + self.enemy.size // 2)
        target_y = int(self.enemy_combat_current_pos[1])

        if is_combo:
            self.enemy_flash_frames = 15
            self.screen_shake_frames = 20
            self.floating_texts.append({
                "text": f"-{damage} COMBO!",
                "x": target_x,
                "y": target_y - 10,
                "timer": 45
            })
            print(f"[Combat] Combo executed! Damage: {damage}. Enemy HP: {self.enemy_hp}")
        else:
            self.enemy_flash_frames = 5
            self.screen_shake_frames = 10
            self.floating_texts.append({
                "text": f"-{damage}",
                "x": target_x,
                "y": target_y - 10,
                "timer": 45
            })
            print(f"[Combat] Attack executed! Damage: {damage}. Enemy HP: {self.enemy_hp}")

    def _trigger_refusal_queue_refill(self):
        """
        Launches a background daemon thread to query LLM for combat excuses and refill the buffer.
        """
        if not self.saif_recruited:
            return
        print("[LLM Buffer] Refilling refusal queue in background...")
        game_state = {
            "player_hp": self.player_hp,
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "saif_hp": self.saif_hp,
            "chat_history": self.chat_history,
            "llm_provider": self.llm_provider,
            "ollama_model": self.ollama_model,
            "ollama_url": self.ollama_url,
            "api_base_url": self.api_base_url,
            "api_model": self.api_model,
            "llm_think": self.llm_think,
            "global_flags": self.global_flags
        }
        t = threading.Thread(target=self._async_fetch_refusal_dialogue, args=(game_state,))
        t.daemon = True
        t.start()

    def _async_fetch_refusal_dialogue(self, game_state: dict):
        """
        Background task executing fetch_refusal_dialogue and appending responses to self.saif_refusal_queue.
        """
        recent_chat = game_state.get("chat_history", [])[-3:]
        excuses = fetch_refusal_dialogue(game_state, recent_chat)
        if excuses:
            self.saif_refusal_queue.extend(excuses)
            self.saif_refusal_queue = self.saif_refusal_queue[:3]
            self._save_game_state()
            print(f"[LLM Buffer] Refilled refusal queue. Current size: {len(self.saif_refusal_queue)}")

    def _trigger_saif_defiance(self, commanded_action: str):
        """
        Triggers Saif's defiance check failure.
        Chooses a rogue action (Self-Heal if potion is available, else Defend).
        Plays feedback sound/VFX, pops pre-fetched excuse instantly from queue.
        """
        potions = self.inventory.get("health_potion", 0)
        if potions > 0:
            action_name = "Self-Heal"
            self.inventory["health_potion"] = potions - 1
            self.saif_hp = min(self.saif_max_hp, self.saif_hp + 50)
            
            # Spawn green healing text
            self.floating_texts.append({
                "text": "+50 HP",
                "x": self.saif_combat_pos[0] + self.player.size // 2,
                "y": self.saif_combat_pos[1],
                "timer": 90,
                "color": (46, 139, 87)
            })
            print(f"[Combat] Saif disobeyed and used a Potion! Saif HP: {self.saif_hp}")
        else:
            action_name = "Defend"
            self.saif_defending = True
            print("[Combat] Saif disobeyed and defended!")
            
        # Spawn Crimson Red "REFUSED!" floating text
        self.floating_texts.append({
            "text": "REFUSED!",
            "x": self.saif_combat_pos[0] + self.player.size // 2,
            "y": self.saif_combat_pos[1] - 20,
            "timer": 90,
            "color": (220, 20, 60)
        })
        
        # Audio / Screen shake feedback
        self.sound_manager.play_sfx("menu_select")
        self.screen_shake_frames = 15
        
        # Instant Execution
        if len(self.saif_refusal_queue) > 0:
            excuse = self.saif_refusal_queue.pop(0)
            self._save_game_state()
        else:
            excuse = 'Not happening.'
            print("Not happening.")
            
        self.saif_excuse_active = True
        self.saif_excuse_text = excuse
        self.saif_excuse_load_time = pygame.time.get_ticks()
        
        # Auto-Refill Check
        if len(self.saif_refusal_queue) < 2:
            self._trigger_refusal_queue_refill()

        # Immediately transition to the next turn (which is the enemy's turn)
        self._end_current_turn()

    def _end_battle_victory(self):
        """
        Ends the battle in victory, transitions back to overworld, and knocks back player.
        """
        print("Battle Over! Victory achieved.")
        self._reset_combat_only_state()
        self.current_location = "overworld"
        self.state = 'exploration_state'
        self._knockback_player()

    def _trigger_victory(self):
        """
        Awards EXP, processes level up, sets up victory screen state, and triggers feedback.
        """
        self.is_combat_ending = True
        self.combat_ending_type = 'victory'
        self.combat_ending_start_time = pygame.time.get_ticks()
        self.sound_manager.play_bgm(None) # Stop BGM music
        self.combat_ui_offset = 200.0 # Hide UI
        self.enemy_defeated_and_removed = True
        
        self.combat_mode = 'victory'
        self.victory_start_time = pygame.time.get_ticks()
        
        # Trigger quest flags if defeating desert_bandit
        if hasattr(self, "enemy_type") and self.enemy_type == "desert_bandit":
            if hasattr(self, "quest_manager") and self.quest_manager:
                self.quest_manager.set_flag("desert_boss_defeated", True)
        
        # Award 50 EXP to player
        self.player_exp += 50
        print(f"[Combat] Enemy defeated! Gained 50 EXP. Total EXP: {self.player_exp}")
        
        # Spawn floating +50 EXP text at the player position
        self.floating_texts.append({
            "text": "+50 EXP",
            "x": self.player_combat_pos[0] + self.player.size // 2,
            "y": self.player_combat_pos[1],
            "timer": 90
        })
        
        # Check player level up
        self.levelled_up = False
        while self.player_exp >= self.exp_to_next_level:
            self.player_exp -= self.exp_to_next_level
            self.player_level += 1
            self.exp_to_next_level = int(self.exp_to_next_level * 1.5)
            self.player_max_hp += 10
            self.player_base_damage += 10
            self.player_hp = self.player_max_hp
            self.levelled_up = True
            
        if self.levelled_up:
            print(f"[Combat] LEVEL UP! Player is now Level {self.player_level}!")
            self.screen_shake_frames = 30
            self.floating_texts.append({
                "text": "LEVEL UP!",
                "x": self.player_combat_pos[0] + self.player.size // 2,
                "y": self.player_combat_pos[1] - 20,
                "timer": 90
            })
            self.sound_manager.play_sfx("parry")
            
        # Award 50 EXP to Saif (if recruited)
        self.saif_levelled_up = False
        if self.saif_recruited:
            self.saif_exp += 50
            print(f"[Combat] Saif Gained 50 EXP. Total EXP: {self.saif_exp}")
            
            # Spawn floating +50 EXP text at Saif's position
            self.floating_texts.append({
                "text": "+50 EXP",
                "x": self.saif_combat_pos[0] + self.player.size // 2,
                "y": self.saif_combat_pos[1],
                "timer": 90
            })
            
            # Check Saif level up
            while self.saif_exp >= self.saif_exp_to_next_level:
                self.saif_exp -= self.saif_exp_to_next_level
                self.saif_level += 1
                self.saif_exp_to_next_level = int(self.saif_exp_to_next_level * 1.5)
                self.saif_max_hp += 10
                self.saif_base_damage += 10
                self.saif_hp = self.saif_max_hp
                self.saif_levelled_up = True
                
            if self.saif_levelled_up:
                print(f"[Combat] LEVEL UP! Saif is now Level {self.saif_level}!")
                self.screen_shake_frames = 30
                self.floating_texts.append({
                    "text": "LEVEL UP!",
                    "x": self.saif_combat_pos[0] + self.player.size // 2,
                    "y": self.saif_combat_pos[1] - 20,
                    "timer": 90
                })
                # Play sound placeholder if not already played for player
                if not self.levelled_up:
                    self.sound_manager.play_sfx("parry")
            
        self._save_game_state()

    def _process_chat_input(self, in_combat: bool):
        """
        Handles the shared chat submission logic for both overworld dialogue
        and combat Talk mode: queries LLM, applies respect, updates history,
        and transitions to the response display state.
        """
        if not self.chat_input_text.strip():
            return

        game_state = {
            "player_hp": self.player_hp,
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "saif_hp": self.saif_hp,
            "chat_history": self.chat_history,
            "in_combat": in_combat,
            "current_location": self.current_location,
            "llm_provider": self.llm_provider,
            "ollama_model": self.ollama_model,
            "ollama_url": self.ollama_url,
            "api_base_url": self.api_base_url,
            "api_model": self.api_model,
            "llm_think": self.llm_think,
            "global_flags": self.global_flags
        }
        res_dict = generate_llm_response(self.chat_input_text, game_state)
        dialogue = res_dict.get("dialogue", "Saif remains silent.")
        change = res_dict.get("respect_change", 0)

        # Apply respect change
        self._adjust_respect(change)

        # Append exchange to rolling chat history and limit to most recent 3
        self.chat_history.append([self.chat_input_text, dialogue])
        if len(self.chat_history) > 3:
            self.chat_history.pop(0)

        self._save_game_state()
        print(f"\n[Debug Memory] Current chat_history: {self.chat_history}\n")

        self.talk_response_text = dialogue
        self.talk_response_start_time = pygame.time.get_ticks()
        self.combat_mode = 'talk_response'

    def _finish_dialogue_response(self, force_exit=False):
        """Instantly finishes the dialogue response display, applying recruitment and returning control."""
        if self.saif_recruited or self.saif_respect >= 40:
            if not self.saif_recruited:
                print("Saif joined the party!")
                self.saif_recruited = True
                self.saif_hp = self.saif_max_hp
                self._save_game_state()
            if self.active_camp_npc == 'saif':
                self.state = 'camp_state'
            else:
                self.state = 'exploration_state'
            self.combat_mode = 'menu'
        else:
            if force_exit:
                if self.active_camp_npc == 'saif':
                    self.state = 'camp_state'
                else:
                    self.state = 'exploration_state'
                self.combat_mode = 'menu'
            else:
                self.combat_mode = 'talk_input'
                self.chat_input_text = ""

    def _load_game_state(self):
        """
        Loads player and enemy HP, respect, inventory, and LLM configuration parameters from the data/game_state.json file.
        Creates default values if the file doesn't exist.
        """
        os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
        
        # Initialize defaults in memory
        self.chat_history = []
        self.chest_opened = False
        self.saif_recruited = False
        self.llm_provider = "ollama"
        self.ollama_model = "gemma4:e4b"
        self.ollama_url = "http://localhost:11434"
        self.api_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        self.api_model = "gemini-2.5-flash"
        self.llm_think = True
        self.inventory = {"health_potion": 0}
        self.saif_refusal_queue = []
        self.current_location = "overworld"
        self.global_flags = {}
        self.player_max_hp = 100
        self.player_level = 1
        self.player_exp = 0
        self.exp_to_next_level = 100
        self.player_base_damage = 20
        self.saif_max_hp = 100
        self.saif_level = 1
        self.saif_exp = 0
        self.saif_exp_to_next_level = 100
        self.saif_base_damage = 15
        
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                    self.player_max_hp = data.get("player_max_hp", 100)
                    self.player_base_damage = data.get("player_base_damage", 20)
                    self.player_level = data.get("player_level", 1)
                    self.player_exp = data.get("player_exp", 0)
                    self.exp_to_next_level = data.get("exp_to_next_level", 100)
                    self.player_hp = data.get("player_hp", self.player_max_hp)
                    self.saif_max_hp = data.get("saif_max_hp", 100)
                    self.saif_base_damage = data.get("saif_base_damage", 15)
                    self.saif_level = data.get("saif_level", 1)
                    self.saif_exp = data.get("saif_exp", 0)
                    self.saif_exp_to_next_level = data.get("saif_exp_to_next_level", 100)
                    self.saif_hp = data.get("saif_hp", self.saif_max_hp)
                    self.enemy_hp = data.get("enemy_hp", 100)
                    self.saif_respect = data.get("saif_respect", 50)
                    self.saif_hp = data.get("saif_hp", 100)
                    self.chest_opened = data.get("chest_opened", False)
                    self.saif_recruited = data.get("saif_recruited", False)
                    self.chat_history = data.get("chat_history", [])
                    self.llm_provider = data.get("llm_provider", self.llm_provider)
                    self.ollama_model = data.get("ollama_model", self.ollama_model)
                    self.ollama_url = data.get("ollama_url", self.ollama_url)
                    self.api_base_url = data.get("api_base_url", self.api_base_url)
                    self.api_model = data.get("api_model", self.api_model)
                    self.llm_think = data.get("llm_think", self.llm_think)
                    self.inventory = data.get("inventory", self.inventory)
                    self.saif_refusal_queue = data.get("saif_refusal_queue", [])[:3]
                    self.current_location = data.get("current_location", "overworld")
                    self.global_flags = data.get("global_flags", {})
                    # Ensure default flags are present
                    if "started_desert_quest" not in self.global_flags:
                        self.global_flags["started_desert_quest"] = True
                    if "desert_boss_defeated" not in self.global_flags:
                        self.global_flags["desert_boss_defeated"] = False
                    
                    # Load enemy state based on boss defeated flag
                    if self.global_flags.get("desert_boss_defeated"):
                        self.enemy = None
                        self.enemy_defeated_and_removed = True
                    else:
                        self.enemy_defeated_and_removed = False
                        self._setup_enemy()
            except Exception as e:
                print(f"[Error] Failed to load JSON state: {e}. Resetting defaults.")
                self._reset_state_to_default()
        else:
            self._reset_state_to_default()

    def _reset_state_to_default(self):
        """
        Resets active game variables in memory while preserving custom LLM and inventory configurations,
        and commits them back to JSON.
        """
        self.player_max_hp = 100
        self.player_base_damage = 20
        self.player_level = 1
        self.player_exp = 0
        self.exp_to_next_level = 100
        self.player_hp = 100
        self.enemy_hp = 100
        self.saif_respect = 50
        self.saif_hp = 100
        self.saif_max_hp = 100
        self.saif_level = 1
        self.saif_exp = 0
        self.saif_exp_to_next_level = 100
        self.saif_base_damage = 15
        self.chest_opened = False
        self.saif_recruited = False
        self.chat_history = []
        self.inventory = {"health_potion": 0}
        self.saif_refusal_queue = []
        self.current_location = "overworld"
        self.global_flags = {"started_desert_quest": True, "desert_boss_defeated": False}
        self.enemy_defeated_and_removed = False
        self._setup_enemy()
        
        # Load and preserve config keys from file if it exists
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                    self.llm_provider = data.get("llm_provider", self.llm_provider)
                    self.ollama_model = data.get("ollama_model", self.ollama_model)
                    self.ollama_url = data.get("ollama_url", self.ollama_url)
                    self.api_base_url = data.get("api_base_url", self.api_base_url)
                    self.api_model = data.get("api_model", self.api_model)
                    self.llm_think = data.get("llm_think", self.llm_think)
                    self.inventory = data.get("inventory", self.inventory)
            except Exception:
                pass
                
        self._save_game_state()

    def _save_game_state(self):
        """
        Saves current memory parameters and configuration values back to the external data/game_state.json file.
        """
        data = {
            "player_hp": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "player_base_damage": self.player_base_damage,
            "player_level": self.player_level,
            "player_exp": self.player_exp,
            "exp_to_next_level": self.exp_to_next_level,
            "saif_hp": self.saif_hp,
            "saif_max_hp": self.saif_max_hp,
            "saif_base_damage": self.saif_base_damage,
            "saif_level": self.saif_level,
            "saif_exp": self.saif_exp,
            "saif_exp_to_next_level": self.saif_exp_to_next_level,
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "chest_opened": self.chest_opened,
            "saif_recruited": self.saif_recruited,
            "chat_history": self.chat_history,
            "llm_provider": self.llm_provider,
            "ollama_model": self.ollama_model,
            "ollama_url": self.ollama_url,
            "api_base_url": self.api_base_url,
            "api_model": self.api_model,
            "llm_think": self.llm_think,
            "inventory": self.inventory,
            "saif_refusal_queue": self.saif_refusal_queue,
            "current_location": self.current_location,
            "global_flags": self.global_flags
        }
        try:
            with open(self.state_file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Error] Failed to save JSON state: {e}")

    def _save_to_save_slot_1(self):
        """
        Dumps the entire current game_state dictionary into save_slot_1.json
        in the project root using Python's json library.
        """
        save_data = {
            "player_hp": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "player_base_damage": self.player_base_damage,
            "player_level": self.player_level,
            "player_exp": self.player_exp,
            "exp_to_next_level": self.exp_to_next_level,
            "saif_hp": self.saif_hp,
            "saif_max_hp": self.saif_max_hp,
            "saif_base_damage": self.saif_base_damage,
            "saif_level": self.saif_level,
            "saif_exp": self.saif_exp,
            "saif_exp_to_next_level": self.saif_exp_to_next_level,
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "chest_opened": self.chest_opened,
            "saif_recruited": self.saif_recruited,
            "chat_history": self.chat_history,
            "llm_provider": self.llm_provider,
            "ollama_model": self.ollama_model,
            "ollama_url": self.ollama_url,
            "api_base_url": self.api_base_url,
            "api_model": self.api_model,
            "llm_think": self.llm_think,
            "inventory": self.inventory,
            "saif_refusal_queue": self.saif_refusal_queue,
            "player_x": self.player.x,
            "player_y": self.player.y,
            "camera_x": self.camera_x,
            "camera_y": self.camera_y,
            "current_location": self.current_location,
            "global_flags": self.global_flags
        }
        try:
            with open(self.save_slot_file, 'w') as f:
                json.dump(save_data, f, indent=2)
            print(f"[System] Game saved successfully to {self.save_slot_file}")
        except Exception as e:
            print(f"[Error] Failed to write save file: {e}")

    def _load_from_save_slot_1(self):
        """
        Loads state from save_slot_1.json, overwriting active memory.
        """
        if os.path.exists(self.save_slot_file):
            try:
                with open(self.save_slot_file, 'r') as f:
                    data = json.load(f)
                    self.player_max_hp = data.get("player_max_hp", 100)
                    self.player_base_damage = data.get("player_base_damage", 20)
                    self.player_level = data.get("player_level", 1)
                    self.player_exp = data.get("player_exp", 0)
                    self.exp_to_next_level = data.get("exp_to_next_level", 100)
                    self.player_hp = data.get("player_hp", self.player_max_hp)
                    self.saif_max_hp = data.get("saif_max_hp", 100)
                    self.saif_base_damage = data.get("saif_base_damage", 15)
                    self.saif_level = data.get("saif_level", 1)
                    self.saif_exp = data.get("saif_exp", 0)
                    self.saif_exp_to_next_level = data.get("saif_exp_to_next_level", 100)
                    self.saif_hp = data.get("saif_hp", self.saif_max_hp)
                    self.enemy_hp = data.get("enemy_hp", 100)
                    self.saif_respect = data.get("saif_respect", 50)
                    self.saif_hp = data.get("saif_hp", 100)
                    self.chest_opened = data.get("chest_opened", False)
                    self.saif_recruited = data.get("saif_recruited", False)
                    self.chat_history = data.get("chat_history", [])
                    self.llm_provider = data.get("llm_provider", self.llm_provider)
                    self.ollama_model = data.get("ollama_model", self.ollama_model)
                    self.ollama_url = data.get("ollama_url", self.ollama_url)
                    self.api_base_url = data.get("api_base_url", self.api_base_url)
                    self.api_model = data.get("api_model", self.api_model)
                    self.llm_think = data.get("llm_think", self.llm_think)
                    self.inventory = data.get("inventory", self.inventory)
                    self.saif_refusal_queue = data.get("saif_refusal_queue", [])[:3]
                    self.player.x = data.get("player_x", 960)
                    self.player.y = data.get("player_y", 1040)
                    self.camera_x = data.get("camera_x", 0.0)
                    self.camera_y = data.get("camera_y", 0.0)
                    self.current_location = data.get("current_location", "overworld")
                    self.global_flags = data.get("global_flags", {})
                    # Ensure default flags are present
                    if "started_desert_quest" not in self.global_flags:
                        self.global_flags["started_desert_quest"] = True
                    if "desert_boss_defeated" not in self.global_flags:
                        self.global_flags["desert_boss_defeated"] = False
                
                # Align map grid tiles
                if self.chest_opened and self.chest_x is not None:
                    c_idx = int(self.chest_x // self.tile_size)
                    r_idx = int(self.chest_y // self.tile_size)
                    self.map_grid[r_idx][c_idx] = 0
                elif not self.chest_opened and self.chest_x is not None:
                    c_idx = int(self.chest_x // self.tile_size)
                    r_idx = int(self.chest_y // self.tile_size)
                    self.map_grid[r_idx][c_idx] = 2

                # Sync to game_state.json so autosaves are updated
                self._save_game_state()
                print(f"[System] Game loaded successfully from {self.save_slot_file}")
            except Exception as e:
                print(f"[Error] Failed to load JSON state from save slot: {e}")

    def _knockback_player(self):
        """
        Knocks the player back by 80 pixels away from the enemy's position
        to prevent immediate re-triggering of combat, ensuring no wall overlaps
        and allowing sliding along obstacles.
        """
        # Calculate direction vector from enemy to player
        if not self.enemy or self.enemy_defeated_and_removed:
            return
        dx = self.player.x - self.enemy.x
        dy = self.player.y - self.enemy.y
        
        # Normalize the direction vector
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            dx /= dist
            dy /= dist
        else:
            # Fallback to left knockback if perfectly overlapping
            dx = -1.0
            dy = 0.0
            
        # Perform knockback in small steps to handle wall collisions smoothly
        knockback_distance = 80.0
        step_size = 5.0
        steps = int(knockback_distance / step_size)
        
        for _ in range(steps):
            # Try horizontal step
            self.player.x += dx * step_size
            self.player.clamp_to_screen(self.world_width, self.world_height)
            if self.player.check_wall_collisions(self.map_grid, self.saif_recruited):
                # Collision: Revert horizontal step
                self.player.x -= dx * step_size
                
            # Try vertical step
            self.player.y += dy * step_size
            self.player.clamp_to_screen(self.world_width, self.world_height)
            if self.player.check_wall_collisions(self.map_grid, self.saif_recruited):
                # Collision: Revert vertical step
                self.player.y -= dy * step_size
                
        self._save_game_state()

    def _transition_to_camp(self):
        """Saves overworld state and transitions player into the 2D Camp Map."""
        self.overworld_player_x = self.player.x
        self.overworld_player_y = self.player.y
        self.overworld_camera_x = self.camera_x
        self.overworld_camera_y = self.camera_y
        
        # Switch map representation to Camp Map (50x50)
        self.map_grid = self.camp_map_grid
        
        # Reset rest notification flag
        self.rest_notification_active = False
        self.elena_dialogue_active = False
        self.active_camp_npc = None
        
        # Spawn player below the campfire facing it
        self.player.x = 960
        self.player.y = 1160
        
        # Recalculate camera centering for campsite
        self._update_camera()
        self.current_location = "camp"
        self.state = 'camp_state'
        print("[System] Transitioned to large campsite map.")

    def _transition_to_overworld(self):
        """Restores player position and camera and transitions back to Overworld."""
        self.map_grid = self.overworld_map_grid
        
        # Restore coordinates and camera offset
        self.player.x = self.overworld_player_x
        self.player.y = self.overworld_player_y
        self.camera_x = self.overworld_camera_x
        self.camera_y = self.overworld_camera_y
        
        self.current_location = "overworld"
        self.state = 'exploration_state'
        print("[System] Returned to overworld.")

    def _update_bgm(self):
        """
        Updates the background music based on the current location.
        Plays the title theme in the main menu and settings screens.
        """
        target_location = "title" if self.state in ('main_menu_state', 'settings_state') else self.current_location
        if target_location != self.last_bgm_location:
            self.sound_manager.play_bgm(target_location)
            self.last_bgm_location = target_location

    def run(self):
        """
        Starts and coordinates the core game loop.
        Uses delta time for frame-rate independent movement.
        """
        while self.is_running:
            # Calculate delta time (seconds since last frame)
            # Cap the frame rate strictly to 60 FPS
            dt = self.clock.tick(60) / 1000.0
            
            # 1. Input/Event handling
            self._handle_events()
            
            # 2. Update state
            self._update(dt)
            
            # 3. Render frame
            self._render()
            
        # Clean shutdown once running loop terminates
        pygame.quit()
        sys.exit()

    def _handle_events(self):
        """
        Processes Pygame events and dispatches KEYDOWN events
        to the appropriate state-specific handler.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.is_running = False
            elif event.type == pygame.KEYDOWN:
                if self.state == 'main_menu_state':
                    self._handle_main_menu_events(event)
                elif self.state == 'pause_menu_state':
                    self._handle_pause_menu_events(event)
                elif self.state == 'camp_state':
                    self._handle_camp_events(event)
                elif self.state == 'settings_state':
                    self._handle_settings_events(event)
                elif self.state == 'exploration_state':
                    self._handle_exploration_events(event)
                elif self.state == 'dialogue_state':
                    self._handle_dialogue_events(event)
                elif self.state == 'combat_state':
                    if not self.is_sliding and not self.is_combat_ending:
                        self._handle_combat_events(event)

    # ── State-specific event handlers ────────────────────────────────────

    def _handle_camp_events(self, event):
        """Handles KEYDOWN events while in the active 2D Camp Map."""
        if self.elena_dialogue_active:
            if event.key == pygame.K_ESCAPE:
                self.elena_dialogue_active = False
                self.active_camp_npc = None
            elif event.key == pygame.K_h:
                # Elena cooks and gifts a Health Potion!
                self.inventory["health_potion"] = self.inventory.get("health_potion", 0) + 1
                self._save_game_state()
                print("[Elena] Cooking Potion! Gifted to player.")
                self.elena_dialogue_active = False
                self.active_camp_npc = None
            return

        if event.key == pygame.K_ESCAPE:
            self._transition_to_overworld()
        elif event.key == pygame.K_e:
            # Check interaction with campfire tile 4 in camp map coordinates
            dist_x = abs(self.player.x - self.campfire_pos[0])
            dist_y = abs(self.player.y - self.campfire_pos[1])
            if dist_x <= 45 and dist_y <= 45:
                self.player_hp = self.player_max_hp
                self.saif_hp = self.saif_max_hp
                self.rest_notification_active = True
                self._save_game_state()
                print("The party rested at the fire. HP fully restored!")
                return

            # Check interaction with Saif (only if recruited) in camp map coordinates
            if self.saif_recruited:
                dist_x = abs(self.player.x - self.saif_camp_pos[0])
                dist_y = abs(self.player.y - self.saif_camp_pos[1])
                if dist_x <= 45 and dist_y <= 45:
                    self.state = 'dialogue_state'
                    self.combat_mode = 'talk_input'
                    self.active_camp_npc = 'saif'
                    self.chat_input_text = ""
                    self.talk_response_text = ""
                    print("[System] Entered dialogue with Saif at camp.")
                    return

            # Check interaction with Elena in camp map coordinates
            dist_x = abs(self.player.x - self.elena_camp_pos[0])
            dist_y = abs(self.player.y - self.elena_camp_pos[1])
            if dist_x <= 45 and dist_y <= 45:
                self.elena_dialogue_active = True
                self.active_camp_npc = 'elena'
                print("[System] Interacted with Elena.")

    def _handle_exploration_events(self, event):
        """Handles KEYDOWN events while exploring the overworld."""
        if event.key == pygame.K_ESCAPE:
            self.state = 'pause_menu_state'
            self.pause_menu_index = 0
            self.save_confirmed_time = 0
        elif event.key == pygame.K_c:
            self._transition_to_camp()
        elif event.key == pygame.K_e:
            # 1. Check adjacency to Saif NPC in world space (adjacent is <= 45px distance)
            if not self.saif_recruited and self.saif_npc_x is not None:
                dist_x = abs(self.player.x - self.saif_npc_x)
                dist_y = abs(self.player.y - self.saif_npc_y)
                if dist_x <= 45 and dist_y <= 45:
                    self.state = 'dialogue_state'
                    self.combat_mode = 'talk_input'
                    self.chat_input_text = ""
                    self.talk_response_text = ""
                    print("[System] Entered overworld dialogue with Saif.")

            # 2. Check adjacency to Chest (tile 2) in world space (adjacent is <= 45px distance)
            if self.chest_x is not None:
                c_idx = int(self.chest_x // self.tile_size)
                r_idx = int(self.chest_y // self.tile_size)
                if self.map_grid[r_idx][c_idx] == 2:
                    dist_x = abs(self.player.x - self.chest_x)
                    dist_y = abs(self.player.y - self.chest_y)
                    if dist_x <= 45 and dist_y <= 45:
                        # Clear map cell from 2 to 0
                        self.map_grid[r_idx][c_idx] = 0
                        self.chest_opened = True
                        # Increment health_potion in inventory
                        self.inventory["health_potion"] = self.inventory.get("health_potion", 0) + 1
                        self._save_game_state()
                        print("Found a Health Potion!")

    def _handle_pause_menu_events(self, event):
        """Handles KEYDOWN events while in the overworld Pause Menu."""
        if event.key == pygame.K_UP:
            self.pause_menu_index = (self.pause_menu_index - 1) % len(self.pause_menu_options)
            self.sound_manager.play_sfx("menu_select")
        elif event.key == pygame.K_DOWN:
            self.pause_menu_index = (self.pause_menu_index + 1) % len(self.pause_menu_options)
            self.sound_manager.play_sfx("menu_select")
        elif event.key == pygame.K_ESCAPE:
            self.state = 'exploration_state'
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            selection = self.pause_menu_options[self.pause_menu_index]
            if selection == "Resume":
                self.state = 'exploration_state'
            elif selection == "Save Game":
                self._save_to_save_slot_1()
                self.save_confirmed_time = pygame.time.get_ticks()
            elif selection == "Quit to Main Menu":
                self.state = 'main_menu_state'
                # Refresh save status when returning to menu
                self.save_exists = os.path.exists(self.save_slot_file)
                if not self.save_exists:
                    self.main_menu_index = 0
                else:
                    self.main_menu_index = 1

    def _handle_main_menu_events(self, event):
        """Handles KEYDOWN events on the Main Menu."""
        if event.key == pygame.K_UP:
            self.main_menu_index = (self.main_menu_index - 1) % len(self.main_menu_options)
            self.sound_manager.play_sfx("menu_select")
        elif event.key == pygame.K_DOWN:
            self.main_menu_index = (self.main_menu_index + 1) % len(self.main_menu_options)
            self.sound_manager.play_sfx("menu_select")
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            selection = self.main_menu_options[self.main_menu_index]
            
            if selection == "New Game":
                from main import reset_game_state
                reset_game_state() # Overwrites game_state.json with defaults
                self._load_game_state() # Load defaults in memory
                
                # Reset map grid copies from DataManager templates
                overworld_data = self.data_manager.get_map_data("overworld") if self.data_manager else None
                camp_data = self.data_manager.get_map_data("camp") if self.data_manager else None
                if overworld_data:
                    self.overworld_map_grid = [list(row) for row in overworld_data["grid"]]
                if camp_data:
                    self.camp_map_grid = [list(row) for row in camp_data["grid"]]
                self.map_grid = self.overworld_map_grid
                
                self.current_location = "overworld"
                
                # Reset starting positions from DataManager Atlas
                player_x = 960
                player_y = 1040
                if overworld_data and "player_spawn" in overworld_data:
                    player_x = overworld_data["player_spawn"][0] * self.tile_size
                    player_y = overworld_data["player_spawn"][1] * self.tile_size
                self.player.x, self.player.y = player_x, player_y
                
                self.enemy_hp = 100
                self.player_hp = self.player_max_hp
                self.saif_hp = self.saif_max_hp
                self._update_camera()
                
                # Switch to loader state
                self.state = 'game_load_state'
                self.load_progress = 0.0
                self.prewarm_complete = False
                self.prewarm_success = False
                
                # Spawn pre-warm thread
                game_state = {
                    "llm_provider": self.llm_provider,
                    "ollama_model": self.ollama_model,
                    "ollama_url": self.ollama_url,
                    "api_base_url": self.api_base_url,
                    "api_model": self.api_model
                }
                def run_prewarm():
                    self.prewarm_success = prewarm_llm(game_state)
                    self.prewarm_complete = True
                
                self.prewarm_thread = threading.Thread(target=run_prewarm)
                self.prewarm_thread.daemon = True
                self.prewarm_thread.start()
                print("[System] Started New Game. Pre-warming LLM...")
            
            elif selection == "Continue":
                if os.path.exists(self.save_slot_file):
                    self._load_from_save_slot_1()
                    
                    # Switch to loader state
                    self.state = 'game_load_state'
                    self.load_progress = 0.0
                    self.prewarm_complete = False
                    self.prewarm_success = False
                    
                    # Spawn pre-warm thread
                    game_state = {
                        "llm_provider": self.llm_provider,
                        "ollama_model": self.ollama_model,
                        "ollama_url": self.ollama_url,
                        "api_base_url": self.api_base_url,
                        "api_model": self.api_model
                    }
                    def run_prewarm():
                        self.prewarm_success = prewarm_llm(game_state)
                        self.prewarm_complete = True
                    
                    self.prewarm_thread = threading.Thread(target=run_prewarm)
                    self.prewarm_thread.daemon = True
                    self.prewarm_thread.start()
                    print("[System] Continuing Game. Pre-warming LLM...")
                else:
                    self.no_save_message_time = pygame.time.get_ticks()
                    print("[System] No save file found.")
                    
            elif selection == "Settings":
                self.state = 'settings_state'
                self.settings_field_index = 0
                self.settings_editing = False
                self.settings_edit_buffer = ""
                # Prepare masked API key display
                api_key = os.environ.get("API_KEY", "")
                if api_key:
                    self.settings_api_key_display = "*" * 8 + api_key[-4:]
                else:
                    self.settings_api_key_display = "(not set)"
                print("[System] Opened LLM Settings from Main Menu.")
                
            elif selection == "Quit":
                self.is_running = False

    def _handle_settings_events(self, event):
        """Handles KEYDOWN events while in the LLM Settings screen."""
        if self.settings_editing:
            # User is typing into a text field
            if event.key == pygame.K_ESCAPE:
                self.settings_editing = False
                self.settings_edit_buffer = ""
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                # Commit the edit
                field = self.settings_fields[self.settings_field_index]
                value = self.settings_edit_buffer.strip()
                if field == 'model' and value:
                    if self.llm_provider == 'ollama':
                        self.ollama_model = value
                    else:
                        self.api_model = value
                    self._save_game_state()
                    print(f"[Settings] Model set to: {value}")
                elif field == 'api_key' and value:
                    save_api_key_to_env(value)
                    self.settings_api_key_display = "*" * 8 + value[-4:]
                    print("[Settings] API key saved securely.")
                self.settings_editing = False
                self.settings_edit_buffer = ""
            elif event.key == pygame.K_BACKSPACE:
                self.settings_edit_buffer = self.settings_edit_buffer[:-1]
            else:
                if event.unicode and ord(event.unicode) >= 32 and len(self.settings_edit_buffer) < 80:
                    self.settings_edit_buffer += event.unicode
        else:
            # Navigation mode
            if event.key == pygame.K_ESCAPE:
                self.state = 'main_menu_state'
                print("[System] Closed LLM Settings.")
            elif event.key == pygame.K_UP:
                self.settings_field_index = (self.settings_field_index - 1) % len(self.settings_fields)
                self.sound_manager.play_sfx("menu_select")
            elif event.key == pygame.K_DOWN:
                self.settings_field_index = (self.settings_field_index + 1) % len(self.settings_fields)
                self.sound_manager.play_sfx("menu_select")
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                field = self.settings_fields[self.settings_field_index]
                if field == 'provider':
                    # Toggle between 'ollama' and 'api'
                    self.llm_provider = 'api' if self.llm_provider == 'ollama' else 'ollama'
                    self._save_game_state()
                    print(f"[Settings] Provider switched to: {self.llm_provider.upper()}")
                elif field == 'think':
                    # Toggle thinking on/off
                    self.llm_think = not self.llm_think
                    self._save_game_state()
                    print(f"[Settings] Thinking set to: {self.llm_think}")
                elif field in ('model', 'api_key'):
                    # Enter text edit mode
                    self.settings_editing = True
                    self.settings_edit_buffer = ""

    def _handle_dialogue_events(self, event):
        """Handles KEYDOWN events during peaceful dialogue with Saif."""
        if self.combat_mode == 'talk_response':
            if event.key == pygame.K_ESCAPE:
                self._finish_dialogue_response(force_exit=True)
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._finish_dialogue_response(force_exit=False)
            return

        if event.key == pygame.K_ESCAPE:
            if self.active_camp_npc == 'saif':
                self.state = 'camp_state'
            else:
                self.state = 'exploration_state'
            self.combat_mode = 'menu'
            print("[System] Left dialogue early.")
        elif self.combat_mode == 'talk_input':
            if event.key == pygame.K_BACKSPACE:
                self.chat_input_text = self.chat_input_text[:-1]
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._process_chat_input(in_combat=False)
            else:
                # Append keyboard inputs
                if event.unicode and ord(event.unicode) >= 32 and len(self.chat_input_text) < 60:
                    self.chat_input_text += event.unicode

    def _handle_combat_events(self, event):
        """Handles KEYDOWN events during the combat state."""
        if self.combat_mode == 'victory':
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE, pygame.K_ESCAPE):
                self._end_battle_victory()
                return

        if event.key == pygame.K_ESCAPE and self.combat_mode == 'menu':
            self.is_running = False

        if self.combat_turn in ('player', 'saif'):
            if self.combat_mode == 'menu':
                self._handle_combat_menu(event)
            elif self.combat_mode == 'talk_input':
                self._handle_combat_talk_input(event)
            elif self.combat_mode == 'item_target':
                self._handle_combat_item_target(event)
            elif self.combat_mode == 'special':
                self._handle_combat_special(event)
            elif self.combat_mode == 'item':
                self._handle_combat_item(event)

        elif self.combat_turn == 'enemy' and self.enemy_attack_active:
            # Press Spacebar to parry (only if player is targeted)
            if event.key == pygame.K_SPACE and self.enemy_target == 'player':
                now = pygame.time.get_ticks()
                elapsed = now - self.enemy_attack_start_time

                if not self.parry_attempted:
                    self.parry_attempted = True
                    # Verify if press is within the scaled 120ms window
                    if self.parry_window_start <= elapsed <= self.parry_window_end:
                        self.parry_success = True
                        print("PERFECT PARRY!")
                    else:
                        self.parry_success = False
                        print("Player took damage!")

    # ── Combat sub-handlers ──────────────────────────────────────────────

    def _handle_combat_menu(self, event):
        """Handles menu navigation and action selection during the player's/Saif's combat turn."""
        # Cycle options with Up / Down arrows
        if event.key == pygame.K_UP:
            self.menu_index = (self.menu_index - 1) % len(self.menu_options)
            self.sound_manager.play_sfx("menu_select")
        elif event.key == pygame.K_DOWN:
            self.menu_index = (self.menu_index + 1) % len(self.menu_options)
            self.sound_manager.play_sfx("menu_select")

        # Enter key triggers option select
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            selected_option = self.menu_options[self.menu_index]

            if selected_option == 'Attack':
                # Trigger slide run attack animations instead of immediate damage
                if self.combat_turn == 'player':
                    self.player_attack_active = True
                    self.player_attack_start_time = pygame.time.get_ticks()
                    self.player_damage_dealt = False
                    self.is_combo_attack = False
                    self.combat_mode = 'menu'
                    self.menu_index = 0
                elif self.combat_turn == 'saif':
                    if self.saif_respect < 70:
                        defiance_check = random.randint(1, 100)
                        if defiance_check > (self.saif_respect + 20):
                            self._trigger_saif_defiance("Attack")
                        else:
                            self.saif_attack_active = True
                            self.saif_attack_start_time = pygame.time.get_ticks()
                            self.saif_damage_dealt = False
                            self.is_combo_attack = False
                            self.combat_mode = 'menu'
                            self.menu_index = 0
                    else:
                        self.saif_attack_active = True
                        self.saif_attack_start_time = pygame.time.get_ticks()
                        self.saif_damage_dealt = False
                        self.is_combo_attack = False
                        self.combat_mode = 'menu'
                        self.menu_index = 0

            elif selected_option == 'Special':
                self.combat_mode = 'special'

            elif selected_option == 'Talk':
                # Enter Talk Input Mode
                self.combat_mode = 'talk_input'
                self.chat_input_text = ""

            elif selected_option == 'Item':
                self.combat_mode = 'item'

            elif selected_option == 'Flee':
                print("Fled from battle! Starting fleeing transition...")
                self.is_combat_ending = True
                self.combat_ending_type = 'flee'
                self.combat_ending_start_time = pygame.time.get_ticks()
                self.sound_manager.play_bgm(None) # Stop battle music
                self.combat_ui_offset = 200.0 # Hide UI
                
                # Define flee targets (slide to the left, off-screen)
                self.player_flee_target = (self.player_combat_current_pos[0] - 300, self.player_combat_current_pos[1])
                self.saif_flee_target = (self.saif_combat_current_pos[0] - 300, self.saif_combat_current_pos[1])

    def _handle_combat_special(self, event):
        """Handles navigation and selection inside the Special sub-menu."""
        if event.key == pygame.K_ESCAPE:
            self.combat_mode = 'menu'
            self.menu_index = 0
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            # Try to trigger Combo Strike
            if self.saif_recruited and self.saif_respect >= 70 and self.combo_cooldown == 0:
                if self.combat_turn == 'saif':
                    if self.saif_respect < 70:
                        defiance_check = random.randint(1, 100)
                        if defiance_check > (self.saif_respect + 20):
                            self._trigger_saif_defiance("Special Combo")
                            return
                
                print("[Combat] Coordinated X-Strike combo initiated!")
                self.combat_mode = 'menu'
                self.menu_index = 0
                
                # Set cooldown to 2 rounds
                self.combo_cooldown = 2
                
                # Start both attack animations
                now = pygame.time.get_ticks()
                self.player_attack_active = True
                self.player_attack_start_time = now
                self.player_damage_dealt = False
                
                self.saif_attack_active = True
                self.saif_attack_start_time = now
                self.saif_damage_dealt = False
                
                self.is_combo_attack = True
                self.combo_damage_applied = False
            elif self.combo_cooldown > 0:
                print(f"[Combat] Cannot execute Combo Strike. Move is on cooldown for {self.combo_cooldown} more round(s)!")
            else:
                print("[Combat] Cannot execute Combo Strike. Requirements (Saif recruited & 70+ Respect) not met.")

    def _handle_combat_item(self, event):
        """Handles navigation and selection inside the Item sub-menu."""
        if event.key == pygame.K_ESCAPE:
            self.combat_mode = 'menu'
            self.menu_index = 0
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            potions = self.inventory.get("health_potion", 0)
            if potions > 0:
                if self.saif_recruited:
                    self.combat_mode = 'item_target'
                    print("[Combat] Item selected. Select target: 1 for Player, 2 for Saif.")
                else:
                    self.inventory["health_potion"] = potions - 1
                    self.player_hp = min(self.player_max_hp, self.player_hp + 50)
                    self._save_game_state()
                    print(f"Used a Health Potion! Restored 50 HP. Player HP: {self.player_hp}")
                    
                    self.combat_mode = 'menu'
                    self.menu_index = 0
                    self._end_current_turn()
            else:
                print("No items left!")

    def _handle_combat_talk_input(self, event):
        """Handles text entry during the combat Talk action."""
        if event.key == pygame.K_ESCAPE:
            # Cancel and return to menu
            self.combat_mode = 'menu'
        elif event.key == pygame.K_BACKSPACE:
            # Delete last character
            self.chat_input_text = self.chat_input_text[:-1]
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._process_chat_input(in_combat=True)
        else:
            # Append key characters (only standard printable text, max 60 characters for multiline input)
            if event.unicode and ord(event.unicode) >= 32 and len(self.chat_input_text) < 60:
                self.chat_input_text += event.unicode

    def _handle_combat_item_target(self, event):
        """Handles target selection when using items during combat."""
        if event.key == pygame.K_ESCAPE:
            self.combat_mode = 'menu'
        elif event.key in (pygame.K_1, pygame.K_KP1):
            potions = self.inventory.get("health_potion", 0)
            if potions > 0:
                self.inventory["health_potion"] = potions - 1
                self.player_hp = min(self.player_max_hp, self.player_hp + 50)
                self._save_game_state()
                print(f"Used a Health Potion! Restored 50 HP to Player. Player HP: {self.player_hp}")
                self.combat_mode = 'menu'
                self._end_current_turn()
        elif event.key in (pygame.K_2, pygame.K_KP2):
            potions = self.inventory.get("health_potion", 0)
            if potions > 0:
                self.inventory["health_potion"] = potions - 1
                self.saif_hp = min(self.saif_max_hp, self.saif_hp + 50)
                self._save_game_state()
                print(f"Used a Health Potion! Restored 50 HP to Saif. Saif HP: {self.saif_hp}")
                self.combat_mode = 'menu'
                self._end_current_turn()


    def _update_camera(self):
        """
        Updates the camera offset so the player remains centered on the screen,
        clamping to the world bounds to prevent scrolling out of the map boundaries.
        """
        player_center_x = self.player.x + self.player.size // 2
        player_center_y = self.player.y + self.player.size // 2
        
        self.camera_x = player_center_x - self.width // 2
        self.camera_y = player_center_y - self.height // 2
        
        # Clamp camera to world map bounds
        self.camera_x = max(0, min(self.camera_x, self.world_width - self.width))
        self.camera_y = max(0, min(self.camera_y, self.world_height - self.height))

    def _update(self, dt: float):
        """
        Updates the state of all active game entities.
        """
        # Maintain background music state
        self._update_bgm()

        # Allow movement/updates in both exploration and camp states
        if self.state in ('exploration_state', 'camp_state'):
            # Fetch the current state of all keyboard buttons
            keys = pygame.key.get_pressed()
            
            saif_rec_check = self.saif_recruited if self.state == 'exploration_state' else False
            
            # Update player movement
            self.player.handle_input(keys, dt, self.world_width, self.world_height, self.map_grid, saif_rec_check)
            
            # Check collision with overworld enemy only in exploration state
            if self.state == 'exploration_state':
                if self.enemy and not self.enemy_defeated_and_removed and self.player.get_collision_rect().colliderect(self.enemy.get_rect()):
                    self.state = 'combat_state'
                    self.current_location = 'combat'
                    self.combat_mode = 'menu'
                    self.combat_turn = 'player'
                    self.menu_index = 0
                    if self.saif_recruited:
                        self.menu_options = ['Attack', 'Special', 'Talk', 'Item', 'Flee']
                    else:
                        self.menu_options = ['Attack', 'Item', 'Flee']
                    
                    # Set starting coordinates at their overworld positions
                    start_player_x = self.player.x - self.camera_x
                    start_player_y = self.player.y - self.camera_y
                    start_enemy_x = self.enemy.x - self.camera_x
                    start_enemy_y = self.enemy.y - self.camera_y
                    
                    self.player_original_screen_pos = (start_player_x, start_player_y)
                    self.clash_start_player_pos = (start_player_x, start_player_y)
                    self.clash_start_enemy_pos = (start_enemy_x, start_enemy_y)
                    self.clash_start_saif_pos = (start_player_x, start_player_y + 80)
                    
                    # Target 'Battle Formation' coordinates (ease-out targets)
                    self.player_combat_pos = (int(0.25 * self.width), 150)
                    self.enemy_combat_start_pos = (int(0.75 * self.width), 190)
                    self.saif_combat_pos = (int(0.25 * self.width), 230)
                    
                    # Initialize starting positions
                    self.player_combat_current_pos = [start_player_x, start_player_y]
                    self.enemy_combat_current_pos = [start_enemy_x, start_enemy_y]
                    self.saif_combat_current_pos = [start_player_x, start_player_y + 80]
                    
                    self.is_sliding = True
                    self.combat_ui_offset = 200.0
                    self.combat_clash_active = True
                    self.combat_clash_start_time = pygame.time.get_ticks()
                    self.combat_clash_hit_triggered = False
                    self.player_attack_active = False
                    self.saif_attack_active = False
                    self.player_damage_dealt = False
                    self.saif_damage_dealt = False
                    self.is_combo_attack = False
                    self.combo_damage_applied = False
                    self.enemy_damage_dealt = False
                    self.combo_cooldown = 0
                    self.saif_defending = False
                    self.saif_excuse_active = False
                    self.saif_excuse_text = ""
                    self.saif_excuse_load_time = None
                    
                    # Clear VFX State
                    self.floating_texts = []
                    self.screen_shake_frames = 0
                    self.enemy_flash_frames = 0
                    self.player_flash_frames = 0
                    self.saif_flash_frames = 0
                    self.player_recoil_frames = 0
                    self.saif_recoil_frames = 0
                    
                    # Trigger background refill thread immediately!
                    self._trigger_refusal_queue_refill()
                    
                    # Start playing the battle music!
                    self._update_bgm()
                    print("Combat Collision! Instantly transitioned to Battle State...")
                
            # Keep camera centered on player
            self._update_camera()

        elif self.state == 'game_load_state':
            # Smooth load progress update
            self.load_progress += 45.0 * dt
            # If pre-warming is not complete yet, pause at 95%
            if self.load_progress >= 95.0 and not self.prewarm_complete:
                self.load_progress = 95.0
            
            # Let it run to 100% once pre-warming is complete
            if self.prewarm_complete and self.load_progress >= 95.0:
                self.load_progress = min(100.0, self.load_progress + 120.0 * dt)
                
            if self.load_progress >= 100.0:
                self.state = 'exploration_state'
            
        # Peaceful dialogue response resolution timer
        elif self.state == 'dialogue_state' and self.combat_mode == 'talk_response':
            now = pygame.time.get_ticks()
            if now - self.talk_response_start_time >= 4000:
                self._finish_dialogue_response(force_exit=False)
                
        elif self.state == 'combat_state':
            if self.is_combat_ending:
                # For victory, wait 1.0 second for text display before reverse Lerp
                if self.combat_ending_type == 'victory':
                    now = pygame.time.get_ticks()
                    if now - self.victory_start_time < 1000:
                        return
                
                # Determine target positions
                if self.combat_ending_type == 'victory':
                    target_player = self.player_original_screen_pos
                    target_saif = (self.player_original_screen_pos[0], self.player_original_screen_pos[1] + 80)
                else:  # Flee
                    target_player = self.player_flee_target
                    target_saif = self.saif_flee_target
                
                # Reverse Lerp (Ease-Out)
                self.player_combat_current_pos[0] += (target_player[0] - self.player_combat_current_pos[0]) * 0.15
                self.player_combat_current_pos[1] += (target_player[1] - self.player_combat_current_pos[1]) * 0.15
                
                if self.saif_recruited:
                    self.saif_combat_current_pos[0] += (target_saif[0] - self.saif_combat_current_pos[0]) * 0.15
                    self.saif_combat_current_pos[1] += (target_saif[1] - self.saif_combat_current_pos[1]) * 0.15
                
                # Check distance
                p_dist = math.hypot(target_player[0] - self.player_combat_current_pos[0], target_player[1] - self.player_combat_current_pos[1])
                
                if p_dist < 2.0:
                    self.player_combat_current_pos = list(target_player)
                    if self.saif_recruited:
                        self.saif_combat_current_pos = list(target_saif)
                    
                    self.is_combat_ending = False
                    self.state = 'exploration_state'
                    self.current_location = 'overworld'
                    
                    # Snap player to overworld grid
                    self.player.x = round(self.player.x / self.tile_size) * self.tile_size
                    self.player.y = round(self.player.y / self.tile_size) * self.tile_size
                    
                    if self.combat_ending_type == 'victory':
                        self.enemy = None  # Remove from entity list
                        self._reset_combat_only_state()
                    else:  # Flee
                        self._knockback_player()
                        # Snap again after knockback
                        self.player.x = round(self.player.x / self.tile_size) * self.tile_size
                        self.player.y = round(self.player.y / self.tile_size) * self.tile_size
                        self._reset_combat_only_state()
                    
                    self._update_camera()
                return # Skip other updates while ending combat

            if self.is_sliding:
                if self.combat_clash_active:
                    now = pygame.time.get_ticks()
                    elapsed = now - self.combat_clash_start_time
                    clash_lunge_duration = 250
                    
                    # Midpoint coordinates
                    mid_x = (self.clash_start_player_pos[0] + self.clash_start_enemy_pos[0]) / 2
                    mid_y = (self.clash_start_player_pos[1] + self.clash_start_enemy_pos[1]) / 2
                    
                    if elapsed < clash_lunge_duration:
                        t = elapsed / clash_lunge_duration
                        # Fast lunge towards midpoint
                        self.player_combat_current_pos[0] = self.clash_start_player_pos[0] + (mid_x - self.clash_start_player_pos[0]) * t
                        self.player_combat_current_pos[1] = self.clash_start_player_pos[1] + (mid_y - self.clash_start_player_pos[1]) * t
                        
                        self.enemy_combat_current_pos[0] = self.clash_start_enemy_pos[0] + (mid_x - self.clash_start_enemy_pos[0]) * t
                        self.enemy_combat_current_pos[1] = self.clash_start_enemy_pos[1] + (mid_y - self.clash_start_enemy_pos[1]) * t
                        
                        self.saif_combat_current_pos[0] = self.clash_start_saif_pos[0] + (mid_x - self.clash_start_saif_pos[0]) * t
                        self.saif_combat_current_pos[1] = self.clash_start_saif_pos[1] + (mid_y - self.clash_start_saif_pos[1]) * t
                    else:
                        # Impact peak!
                        if not self.combat_clash_hit_triggered:
                            self.combat_clash_hit_triggered = True
                            self.sound_manager.play_sfx("hit")
                            self.screen_shake_frames = 20
                            self.player_flash_frames = 8
                            self.enemy_flash_frames = 8
                            self.floating_texts.append({
                                "text": "CLASH!",
                                "x": int(mid_x),
                                "y": int(mid_y - 20),
                                "timer": 60,
                                "color": (238, 206, 112)
                            })
                        
                        # Freeze in place briefly
                        self.player_combat_current_pos[0] = mid_x
                        self.player_combat_current_pos[1] = mid_y
                        self.enemy_combat_current_pos[0] = mid_x
                        self.enemy_combat_current_pos[1] = mid_y
                        self.saif_combat_current_pos[0] = mid_x
                        self.saif_combat_current_pos[1] = mid_y
                        
                        if elapsed >= 400: # 150ms impact freeze
                            self.combat_clash_active = False
                    return # Skip normal updates during clash lunge
                
                # Ease-Out Math (Lerp) - Recoil push back to battle formation
                self.player_combat_current_pos[0] += (self.player_combat_pos[0] - self.player_combat_current_pos[0]) * 0.15
                self.player_combat_current_pos[1] += (self.player_combat_pos[1] - self.player_combat_current_pos[1]) * 0.15
                
                self.enemy_combat_current_pos[0] += (self.enemy_combat_start_pos[0] - self.enemy_combat_current_pos[0]) * 0.15
                self.enemy_combat_current_pos[1] += (self.enemy_combat_start_pos[1] - self.enemy_combat_current_pos[1]) * 0.15
                
                self.saif_combat_current_pos[0] += (self.saif_combat_pos[0] - self.saif_combat_current_pos[0]) * 0.15
                self.saif_combat_current_pos[1] += (self.saif_combat_pos[1] - self.saif_combat_current_pos[1]) * 0.15
                
                # Check distance to target positions (hypot)
                p_dist = math.hypot(self.player_combat_pos[0] - self.player_combat_current_pos[0], self.player_combat_pos[1] - self.player_combat_current_pos[1])
                e_dist = math.hypot(self.enemy_combat_start_pos[0] - self.enemy_combat_current_pos[0], self.enemy_combat_start_pos[1] - self.enemy_combat_current_pos[1])
                s_dist = math.hypot(self.saif_combat_pos[0] - self.saif_combat_current_pos[0], self.saif_combat_pos[1] - self.saif_combat_current_pos[1])
                
                # Snap & Lock
                if p_dist < 2.0 and e_dist < 2.0 and s_dist < 2.0:
                    self.player_combat_current_pos = list(self.player_combat_pos)
                    self.enemy_combat_current_pos = list(self.enemy_combat_start_pos)
                    self.saif_combat_current_pos = list(self.saif_combat_pos)
                    self.is_sliding = False
                    
                    # UI & Audio Trigger
                    self.sound_manager.play_sfx("menu_select")
                return # Skip other updates while sliding
                
            # Slide combat menus up
            if self.combat_ui_offset > 0.0:
                self.combat_ui_offset += (0.0 - self.combat_ui_offset) * 0.15
                if self.combat_ui_offset < 2.0:
                    self.combat_ui_offset = 0.0
 
            # Handle excuse decay timer
            if self.saif_excuse_active and self.saif_excuse_load_time is not None:
                if pygame.time.get_ticks() - self.saif_excuse_load_time >= 4000:
                    self.saif_excuse_active = False
                    self.saif_excuse_text = ""
                    self.saif_excuse_load_time = None
 
            # Handle response delay timer (4 seconds)
            elif self.combat_turn == 'player' and self.combat_mode == 'talk_response':
                now = pygame.time.get_ticks()
                if now - self.talk_response_start_time >= 4000:
                    self.combat_mode = 'menu'
                    self._end_current_turn()
                    
            elif self.combat_turn == 'enemy' and self.enemy_attack_active:
                now = pygame.time.get_ticks()
                elapsed = now - self.enemy_attack_start_time
                
                # Attacking slide animation (forward then backward) using randomized durations
                start_x = self.enemy_combat_start_pos[0]
                target_combat_pos = self.player_combat_pos if self.enemy_target == 'player' else self.saif_combat_pos
                target_x = target_combat_pos[0] + 40 if start_x >= target_combat_pos[0] else target_combat_pos[0] - 40
                target_y = target_combat_pos[1]
                
                # Keep Y-axis aligned with the target
                self.enemy_combat_current_pos[1] = target_y
                
                # Check impact peak (forward_duration) to apply damage and flash!
                if elapsed >= self.forward_duration and not self.enemy_damage_dealt:
                    self.enemy_damage_dealt = True
                    if self.enemy_target == 'player':
                        # Check if player missed parry (didn't parry or failed early/late)
                        if not self.parry_success:
                            if not self.parry_attempted:
                                print("Player took damage!")
                            self.sound_manager.play_sfx("hit")
                            self.player_hp = max(0, self.player_hp - 20)
                            self._save_game_state()
                            # Spawn player damage floating text
                            self.floating_texts.append({
                                "text": "-20",
                                "x": self.player_combat_pos[0] + self.player.size // 2,
                                "y": self.player_combat_pos[1],
                                "timer": 45
                            })
                            # Trigger VFX
                            self.player_flash_frames = 5
                            self.player_recoil_frames = 6
                            self.screen_shake_frames = 10
                        else:
                            # Play parry SFX!
                            self.sound_manager.play_sfx("parry")
                            # Spawn parry text and small shake
                            self.floating_texts.append({
                                "text": "PARRIED!",
                                "x": self.player_combat_pos[0] + self.player.size // 2,
                                "y": self.player_combat_pos[1],
                                "timer": 45
                            })
                            self.screen_shake_frames = 5
                    else:
                        # Saif was targeted: parry is skipped
                        print("Saif took damage!")
                        self.sound_manager.play_sfx("hit")
                        damage = 10 if self.saif_defending else 20
                        self.saif_hp = max(0, self.saif_hp - damage)
                        self._save_game_state()
                        # Spawn Saif damage floating text
                        self.floating_texts.append({
                            "text": f"-{damage}",
                            "x": self.saif_combat_pos[0] + self.player.size // 2,
                            "y": self.saif_combat_pos[1],
                            "timer": 45
                        })
                        # Trigger VFX
                        self.saif_flash_frames = 5
                        self.saif_recoil_frames = 6
                        self.screen_shake_frames = 10

                
                if elapsed < self.forward_duration:
                    t = elapsed / self.forward_duration
                    self.enemy_combat_current_pos[0] = start_x - (start_x - target_x) * t
                elif elapsed < self.total_duration:
                    t = (elapsed - self.forward_duration) / self.forward_duration
                    self.enemy_combat_current_pos[0] = target_x + (start_x - target_x) * t
                else:
                    # Animation finished! Lock position back to start coordinates
                    self.enemy_combat_current_pos[0] = self.enemy_combat_start_pos[0]
                    self.enemy_combat_current_pos[1] = self.enemy_combat_start_pos[1]
                    self.enemy_attack_active = False
                            
                    # Check if either HP hits 0 to end battle
                    if self.player_hp <= 0 or (self.saif_recruited and self.saif_hp <= 0):
                        print("Battle Over! Defeat.")
                        self._reset_combat_only_state()
                        self.current_location = "overworld"
                        self.state = 'exploration_state'
                        self._knockback_player()
                    else:
                        # Reset back to player's turn
                        self.combat_turn = 'player'
                        self.menu_index = 0
                        self.combat_mode = 'menu'
                        
                        # Decrement special cooldown
                        if self.combo_cooldown > 0:
                            self.combo_cooldown -= 1
                            
                        if self.saif_recruited:
                            self.menu_options = ['Attack', 'Special', 'Talk', 'Item', 'Flee']
                        else:
                            self.menu_options = ['Attack', 'Item', 'Flee']

            # Player attack slide animation processing
            if self.player_attack_active:
                now = pygame.time.get_ticks()
                elapsed = now - self.player_attack_start_time
                duration = 600
                half_duration = 300
                start_x = self.player_combat_pos[0]
                target_x = self.enemy_combat_start_pos[0] - 40 if start_x <= self.enemy_combat_start_pos[0] else self.enemy_combat_start_pos[0] + 40
                
                # Keep Y aligned
                self.player_combat_current_pos[1] = self.player_combat_pos[1]
                
                # Slide logic
                if elapsed < half_duration:
                    t = elapsed / half_duration
                    self.player_combat_current_pos[0] = start_x + (target_x - start_x) * t
                elif elapsed < duration:
                    t = (elapsed - half_duration) / half_duration
                    self.player_combat_current_pos[0] = target_x - (target_x - start_x) * t
                else:
                    self.player_combat_current_pos[0] = self.player_combat_pos[0]
                    self.player_attack_active = False
                    
                    if not self.is_combo_attack:
                        if self.enemy_hp <= 0:
                            self._trigger_victory()
                        else:
                            self._end_current_turn()
                    else:
                        # Joint attack check
                        if not self.saif_attack_active:
                            if self.enemy_hp <= 0:
                                self._trigger_victory()
                            else:
                                self.is_combo_attack = False
                                self._start_enemy_turn()

                # Peak hit logic
                if elapsed >= half_duration and not self.player_damage_dealt:
                    self.player_damage_dealt = True
                    if not self.is_combo_attack:
                        # Player solo attack deals player_base_damage
                        self._apply_damage_to_enemy(self.player_base_damage, is_combo=False)
                    else:
                        if not self.combo_damage_applied:
                            self.combo_damage_applied = True
                            self._apply_damage_to_enemy(35, is_combo=True)

            # Saif attack slide animation processing
            if self.saif_attack_active:
                now = pygame.time.get_ticks()
                elapsed = now - self.saif_attack_start_time
                duration = 600
                half_duration = 300
                start_x = self.saif_combat_pos[0]
                target_x = self.enemy_combat_start_pos[0] - 40 if start_x <= self.enemy_combat_start_pos[0] else self.enemy_combat_start_pos[0] + 40
                
                # Keep Y aligned
                self.saif_combat_current_pos[1] = self.saif_combat_pos[1]
                
                # Slide logic
                if elapsed < half_duration:
                    t = elapsed / half_duration
                    self.saif_combat_current_pos[0] = start_x + (target_x - start_x) * t
                elif elapsed < duration:
                    t = (elapsed - half_duration) / half_duration
                    self.saif_combat_current_pos[0] = target_x - (target_x - start_x) * t
                else:
                    self.saif_combat_current_pos[0] = self.saif_combat_pos[0]
                    self.saif_attack_active = False
                    
                    if not self.is_combo_attack:
                        if self.enemy_hp <= 0:
                            self._trigger_victory()
                        else:
                            self._end_current_turn()
                    else:
                        # Joint attack check
                        if not self.player_attack_active:
                            if self.enemy_hp <= 0:
                                self._trigger_victory()
                            else:
                                self.is_combo_attack = False
                                self._start_enemy_turn()

                # Peak hit logic
                if elapsed >= half_duration and not self.saif_damage_dealt:
                    self.saif_damage_dealt = True
                    if not self.is_combo_attack:
                        # Saif solo attack deals saif_base_damage
                        self._apply_damage_to_enemy(self.saif_base_damage, is_combo=False)
                    else:
                        if not self.combo_damage_applied:
                            self.combo_damage_applied = True
                            self._apply_damage_to_enemy(35, is_combo=True)

    def _render(self):
        """
        Clears the screen and draws all current entities.
        """
        # Clear screen with dark mode background
        self.screen.fill(self.bg_color)
        
        if self.state == 'main_menu_state':
            # Draw sleek main menu
            self._draw_prototype_grid()
            
            # Title
            self._draw_text("TEMPORAL RESONANCE", self.width // 2, 150, (238, 206, 112), center=True)
            self._draw_text("Core Engine Prototype", self.width // 2, 180, (150, 150, 155), center=True)
            
            pygame.draw.line(self.screen, self.grid_color, (200, 210), (600, 210), 1)
            
            # Temporary no save warning
            if pygame.time.get_ticks() - self.no_save_message_time < 2000:
                self._draw_text("No save file found!", self.width // 2, 245, (220, 20, 60), center=True)
            
            # Menu Options
            start_y = 300
            spacing = 50
            
            for i, option in enumerate(self.main_menu_options):
                y = start_y + (i * spacing)
                is_selected = (i == self.main_menu_index)
                
                if is_selected:
                    color = (30, 144, 255)
                    text = f"> {option} <"
                    # Draw highlight box
                    pygame.draw.rect(self.screen, (40, 40, 50), pygame.Rect(300, y - 15, 200, 30))
                    pygame.draw.rect(self.screen, (60, 60, 75), pygame.Rect(300, y - 15, 200, 30), 1)
                else:
                    color = (200, 200, 210)
                    text = option
                    
                self._draw_text(text, self.width // 2, y, color, center=True)
                
            # Version/Info
            self._draw_text("Use UP/DOWN to navigate | ENTER to select", self.width // 2, 550, (100, 100, 110), center=True)
            
        elif self.state in ('exploration_state', 'dialogue_state', 'pause_menu_state', 'camp_state', 'combat_state'):
            # Render solid grey walls from map grid first with frustum culling
            if self.map_grid:
                tile_size = self.tile_size
                wall_color = (60, 60, 68)      # Modern slate grey
                border_color = (48, 48, 54)    # Darker grey for tile borders
                
                # Frustum culling: calculate visible range of tiles
                start_col = max(0, int(self.camera_x // tile_size))
                end_col = min(len(self.map_grid[0]), int((self.camera_x + self.width) // tile_size) + 1)
                
                start_row = max(0, int(self.camera_y // tile_size))
                end_row = min(len(self.map_grid), int((self.camera_y + self.height) // tile_size) + 1)
                
                for r_idx in range(start_row, end_row):
                    for c_idx in range(start_col, end_col):
                        cell = self.map_grid[r_idx][c_idx]
                        if cell == 1:
                            # Apply camera offset to wall drawing
                            screen_x = c_idx * tile_size - self.camera_x
                            screen_y = r_idx * tile_size - self.camera_y
                            wall_rect = pygame.Rect(screen_x, screen_y, tile_size, tile_size)
                            pygame.draw.rect(self.screen, wall_color, wall_rect)
                            pygame.draw.rect(self.screen, border_color, wall_rect, 1)
                        elif cell == 4:
                            # Draw solid Orange rectangle
                            screen_x = c_idx * tile_size - self.camera_x
                            screen_y = r_idx * tile_size - self.camera_y
                            camp_rect = pygame.Rect(screen_x, screen_y, tile_size, tile_size)
                            pygame.draw.rect(self.screen, (255, 140, 0), camp_rect)
                            
            # Draw a modern, subtle grid relative to camera offsets for smooth shifting movement
            self._draw_prototype_grid()
            
            # Render Saif NPC on overworld if not recruited (only in overworld!)
            if self.map_grid != self.camp_map_grid and not self.saif_recruited and self.saif_npc_x is not None:
                screen_x = self.saif_npc_x - self.camera_x
                screen_y = self.saif_npc_y - self.camera_y
                pygame.draw.rect(self.screen, (46, 139, 87), pygame.Rect(screen_x, screen_y, self.tile_size, self.tile_size))
            
            # Render game entities with camera offsets (only in overworld!)
            if self.map_grid != self.camp_map_grid:
                if self.state != 'combat_state' and self.enemy and not self.enemy_defeated_and_removed:
                    self.enemy.draw(self.screen, self.camera_x, self.camera_y)
                if self.chest_x is not None:
                    c_idx = int(self.chest_x // self.tile_size)
                    r_idx = int(self.chest_y // self.tile_size)
                    if self.map_grid[r_idx][c_idx] == 2:
                        self.chest.draw(self.screen, self.camera_x, self.camera_y)
            if self.state != 'combat_state':
                self.player.draw(self.screen, self.camera_x, self.camera_y)
            
            # Render Camp entities if in camp map grid
            if self.map_grid == self.camp_map_grid:
                # 1. Flickering Campfire at self.campfire_pos (960, 1040)
                screen_x = self.campfire_pos[0] - self.camera_x
                screen_y = self.campfire_pos[1] - self.camera_y
                if -40 <= screen_x <= self.width and -40 <= screen_y <= self.height:
                    # Draw overlapping logs
                    pygame.draw.rect(self.screen, (101, 67, 33), pygame.Rect(screen_x + 5, screen_y + 15, 30, 10))
                    pygame.draw.rect(self.screen, (101, 67, 33), pygame.Rect(screen_x + 15, screen_y + 5, 10, 30))
                    
                    flicker = int(math.sin(pygame.time.get_ticks() / 80) * 4)
                    # Outer red/orange glow
                    pygame.draw.circle(self.screen, (255, 69, 0), (screen_x + 20, screen_y + 20), 18 + flicker)
                    # Inner flame core
                    pygame.draw.circle(self.screen, (255, 165, 0), (screen_x + 20, screen_y + 20), 11 + flicker // 2)
                    pygame.draw.circle(self.screen, (255, 215, 0), (screen_x + 20, screen_y + 20), 6)
                    
                # 2. Saif at self.saif_camp_pos (880, 1040) - only if recruited!
                if self.saif_recruited:
                    screen_x = self.saif_camp_pos[0] - self.camera_x
                    screen_y = self.saif_camp_pos[1] - self.camera_y
                    if -40 <= screen_x <= self.width and -40 <= screen_y <= self.height:
                        pygame.draw.rect(self.screen, (46, 139, 87), pygame.Rect(screen_x, screen_y, self.tile_size, self.tile_size))
                        
                # 3. Elena the Chef at self.elena_camp_pos (1040, 1040)
                screen_x = self.elena_camp_pos[0] - self.camera_x
                screen_y = self.elena_camp_pos[1] - self.camera_y
                if -40 <= screen_x <= self.width and -40 <= screen_y <= self.height:
                    pygame.draw.rect(self.screen, (218, 112, 214), pygame.Rect(screen_x, screen_y, self.tile_size, self.tile_size))
                    
                # 4. Interaction Prompts
                # Adjacent to campfire?
                dist_x = abs(self.player.x - self.campfire_pos[0])
                dist_y = abs(self.player.y - self.campfire_pos[1])
                if dist_x <= 45 and dist_y <= 45:
                    self._draw_text("Press E to rest at fire", self.width // 2, 80, (255, 140, 0), center=True)

                # Adjacent to Saif?
                if self.saif_recruited:
                    dist_x = abs(self.player.x - self.saif_camp_pos[0])
                    dist_y = abs(self.player.y - self.saif_camp_pos[1])
                    if dist_x <= 45 and dist_y <= 45:
                        self._draw_text("Press E to talk to Saif", self.width // 2, 80, (238, 206, 112), center=True)
                
                # Adjacent to Elena?
                dist_x = abs(self.player.x - self.elena_camp_pos[0])
                dist_y = abs(self.player.y - self.elena_camp_pos[1])
                if dist_x <= 45 and dist_y <= 45:
                    self._draw_text("Press E to talk to Elena", self.width // 2, 80, (238, 206, 112), center=True)
                    
                # 5. Elena's dialogue card overlay
                if self.elena_dialogue_active:
                    pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(150, 420, 500, 160))
                    pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(150, 420, 500, 160), 2)
                    self._draw_text("Elena (Camp Chef):", 170, 435, (218, 112, 214))
                    self._draw_text("Welcome to our cozy fire! Would you like a warm stew,", 170, 470, (245, 245, 245))
                    self._draw_text("or some freshly brewed Health Potion? Press H!", 170, 495, (245, 245, 245))
                    self._draw_text("ESC: Close | H: Take Potion", 170, 545, (150, 150, 150))
                    
                # 6. Campsite bottom HUD
                elif not self.elena_dialogue_active:
                    pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(100, 440, 600, 140))
                    pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(100, 440, 600, 140), 2)
                    
                    self._draw_text("CAMPFIRE COGNIZANCE HUD", 130, 455, (238, 206, 112))
                    self._draw_text("Stand adjacent to fire and press E to Rest | ESC to pack up", 130, 490, (245, 245, 245))
                    
                    hp_status = f"Player (Lv. {self.player_level}) HP: {self.player_hp}/{self.player_max_hp} (EXP: {self.player_exp}/{self.exp_to_next_level})"
                    if self.saif_recruited:
                        hp_status += f"  |  Saif (Lv. {self.saif_level}) HP: {self.saif_hp}/{self.saif_max_hp} (EXP: {self.saif_exp}/{self.saif_exp_to_next_level}) (Respect: {self.saif_respect}/100)"
                    self._draw_text(hp_status, 130, 520, (30, 144, 255))
                    self._draw_text(f"Potions: {self.inventory.get('health_potion', 0)}", 130, 545, (238, 206, 112))
                    
                    if self.rest_notification_active:
                        self._draw_text("The party rested at the fire. HP fully restored!", 350, 455, (46, 139, 87))
            
            # Draw Centered Peaceful Conversation Panel (only in dialogue_state)
            if self.state == 'dialogue_state':
                # Centered panel box outline (X: 150 to 650, Y: 420 to 580)
                pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(150, 420, 500, 160))
                pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(150, 420, 500, 160), 2)
                
                # Header
                self._draw_text(f"Talk to Saif (Respect: {self.saif_respect}/100)", 170, 430, (238, 206, 112))
                
                if self.combat_mode == 'talk_input':
                    # Draw text entry box outline
                    input_box_rect = pygame.Rect(170, 465, 460, 75)
                    pygame.draw.rect(self.screen, (16, 16, 20), input_box_rect)
                    pygame.draw.rect(self.screen, self.grid_color, input_box_rect, 1)
                    
                    # Wrap input text to multiple lines of max 40 characters per line
                    chars_per_line = 40
                    input_lines = [self.chat_input_text[i:i+chars_per_line] for i in range(0, len(self.chat_input_text), chars_per_line)]
                    if not input_lines:
                        input_lines = [""]
                    
                    # Render wrapped text with flashing caret on the last active character
                    for idx, line in enumerate(input_lines):
                        line_caret = ""
                        if idx == len(input_lines) - 1:
                            line_caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
                        self._draw_text(line + line_caret, 180, 475 + idx * 25, (255, 255, 255))
                    
                    # Helper text
                    self._draw_text("ESC: Cancel Dialogue | ENTER: Send", 170, 550, (150, 150, 150))
                    
                elif self.combat_mode == 'talk_response':
                    # Render gold header
                    self._draw_text("Saif:", 170, 465, (238, 206, 112))
                    
                    # Wrap Saif response to 40 characters per line
                    words = self.talk_response_text.split(' ')
                    lines = []
                    current_line = ""
                    for word in words:
                        test_line = current_line + " " + word if current_line else word
                        if len(test_line) < 40:
                            current_line = test_line
                        else:
                            lines.append(current_line)
                            current_line = word
                    if current_line:
                        lines.append(current_line)
                    
                    # Draw dialogue lines
                    for idx, line in enumerate(lines[:3]):
                        self._draw_text(line, 170, 495 + idx * 25, (245, 245, 245))
                    
                    # Helper text (if recruited, show join notice, else show wait)
                    if not self.saif_recruited and self.saif_respect >= 40:
                        self._draw_text("Saif is joining the party...", 170, 550, (46, 139, 87))
                    else:
                        self._draw_text("Please wait...", 170, 550, (150, 150, 150))
            
            # Render Overworld Pause Menu on top if in pause_menu_state
            if self.state == 'pause_menu_state':
                # Create a semi-transparent screen-sized rectangle to dim the overworld
                overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                overlay.fill((10, 10, 15, 180))
                self.screen.blit(overlay, (0, 0))
                
                # Center panel
                pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(200, 180, 400, 240))
                pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(200, 180, 400, 240), 2)
                
                # Title
                self._draw_text("GAME PAUSED", self.width // 2, 210, (238, 206, 112), center=True)
                pygame.draw.line(self.screen, self.grid_color, (230, 235), (570, 235), 1)
                
                # Menu options
                start_y = 260
                spacing = 45
                for i, option in enumerate(self.pause_menu_options):
                    y = start_y + (i * spacing)
                    is_selected = (i == self.pause_menu_index)
                    if is_selected:
                        color = (30, 144, 255)
                        text = f"> {option} <"
                        pygame.draw.rect(self.screen, (40, 40, 50), pygame.Rect(240, y - 12, 320, 28))
                        pygame.draw.rect(self.screen, (60, 60, 75), pygame.Rect(240, y - 12, 320, 28), 1)
                    else:
                        color = (200, 200, 210)
                        text = option
                    self._draw_text(text, self.width // 2, y, color, center=True)
                    
                # Toast notification
                if pygame.time.get_ticks() - self.save_confirmed_time < 2000:
                    self._draw_text("Game Saved Successfully!", self.width // 2, 395, (46, 139, 87), center=True)


            
        elif self.state == 'settings_state':
            # ── LLM Settings Screen ──────────────────────────────────────
            pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(50, 50, 700, 500))
            pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(50, 50, 700, 500), 2)
            
            # Header
            self._draw_text("LLM SETTINGS", 400, 90, (238, 206, 112), center=True)
            pygame.draw.line(self.screen, self.grid_color, (100, 120), (700, 120), 1)
            
            # Current config display
            y_start = 155
            row_height = 70
            
            fields_display = [
                {
                    "key": "provider",
                    "label": "Provider",
                    "value": "Local (Ollama)" if self.llm_provider == "ollama" else "Cloud API",
                    "hint": "ENTER to toggle"
                },
                {
                    "key": "model",
                    "label": "Model",
                    "value": self.ollama_model if self.llm_provider == "ollama" else self.api_model,
                    "hint": "ENTER to edit"
                },
                {
                    "key": "api_key",
                    "label": "API Key",
                    "value": self.settings_api_key_display,
                    "hint": "ENTER to set (saved to .env)"
                },
                {
                    "key": "think",
                    "label": "Thinking",
                    "value": "ON" if self.llm_think else "OFF",
                    "hint": "ENTER to toggle"
                }
            ]
            
            for i, field_info in enumerate(fields_display):
                y_pos = y_start + i * row_height
                is_selected = (i == self.settings_field_index)
                
                # Selection indicator
                if is_selected:
                    # Draw selection highlight bar
                    pygame.draw.rect(self.screen, (40, 40, 50),
                                     pygame.Rect(80, y_pos - 5, 640, row_height - 10))
                    pygame.draw.rect(self.screen, (60, 60, 75),
                                     pygame.Rect(80, y_pos - 5, 640, row_height - 10), 1)
                    label_color = (30, 144, 255)
                    arrow = "> "
                else:
                    label_color = (180, 180, 190)
                    arrow = "  "
                
                # Label
                self._draw_text(f"{arrow}{field_info['label']}:", 100, y_pos, label_color)
                
                # Value — show edit buffer if currently editing this field
                if is_selected and self.settings_editing:
                    caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
                    # Draw edit box
                    edit_rect = pygame.Rect(300, y_pos - 2, 380, 28)
                    pygame.draw.rect(self.screen, (16, 16, 20), edit_rect)
                    pygame.draw.rect(self.screen, (60, 60, 75), edit_rect, 1)
                    display_text = self.settings_edit_buffer
                    # Mask API key input as user types
                    if field_info['key'] == 'api_key' and display_text:
                        display_text = "*" * max(0, len(display_text) - 4) + display_text[-4:]
                    self._draw_text(display_text + caret, 308, y_pos, (255, 255, 255))
                else:
                    value_color = (245, 245, 245) if is_selected else (150, 150, 155)
                    self._draw_text(field_info['value'], 300, y_pos, value_color)
                
                # Hint text
                if is_selected and not self.settings_editing:
                    self._draw_text(field_info['hint'], 300, y_pos + 28, (100, 100, 110))
            
            # Divider
            pygame.draw.line(self.screen, self.grid_color, (100, y_start + 4 * row_height + 10),
                             (700, y_start + 4 * row_height + 10), 1)
            
            # Provider-specific info
            info_y = y_start + 4 * row_height + 30
            if self.llm_provider == "ollama":
                self._draw_text("Ollama URL: " + self.ollama_url, 100, info_y, (100, 100, 110))
                self._draw_text("Ensure Ollama is running locally.", 100, info_y + 25, (100, 100, 110))
            else:
                self._draw_text("API URL: " + self.api_base_url[:55], 100, info_y, (100, 100, 110))
                self._draw_text("Key is stored in .env (gitignored, never in source).", 100, info_y + 25, (100, 100, 110))
            
            # Footer controls
            if self.settings_editing:
                self._draw_text("Type value | ENTER: Confirm | ESC: Cancel", 400, 520, (150, 150, 155), center=True)
            else:
                self._draw_text("UP/DOWN: Navigate | ENTER: Select | ESC: Back to Game", 400, 520, (150, 150, 155), center=True)
        
        # Static camp_state renderer removed because camp is now fully 2D and dynamic.
            
        elif self.state == 'game_load_state':
            # Draw title background elements
            self._draw_prototype_grid()
            
            # Draw sleek panel in center
            panel_rect = pygame.Rect(150, 160, 500, 280)
            pygame.draw.rect(self.screen, self.panel_color, panel_rect)
            pygame.draw.rect(self.screen, self.grid_color, panel_rect, 2)
            
            # Pulsing Title
            title_color = (238, 206, 112) # Gold
            self._draw_text("TEMPORAL RESONANCE", self.width // 2, 190, title_color, center=True)
            
            # Custom status text depending on progress
            status_text = "Calibrating Resonance..."
            if self.load_progress < 30:
                status_text = "Initializing core variables..."
            elif self.load_progress < 60:
                status_text = "Loading overworld maps..."
            elif self.load_progress < 95:
                status_text = "Pre-heating LLM cognitive core..."
            elif self.load_progress < 100:
                if not self.prewarm_complete:
                    status_text = "Warming up local LLM core (takes 5-15s)..."
                else:
                    status_text = "LLM core online. Handshake established!"
            else:
                status_text = "Temporal connection open!"
                
            self._draw_text(status_text, self.width // 2, 240, (200, 200, 210), center=True)
            
            # Draw Progress Bar
            bar_width = 360
            bar_height = 14
            bar_x = (self.width - bar_width) // 2
            bar_y = 290
            
            # Background
            pygame.draw.rect(self.screen, (30, 30, 36), pygame.Rect(bar_x, bar_y, bar_width, bar_height))
            pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(bar_x, bar_y, bar_width, bar_height), 1)
            
            # Fill
            fill_width = int(bar_width * (self.load_progress / 100.0))
            if fill_width > 0:
                pygame.draw.rect(self.screen, (30, 144, 255), pygame.Rect(bar_x + 1, bar_y + 1, fill_width - 2, bar_height - 2))
                
            # Percentage text
            self._draw_text(f"{int(self.load_progress)}%", self.width // 2, 325, (30, 144, 255), center=True)
            
            # Small spinner or micro-animation
            angle = pygame.time.get_ticks() / 150.0
            spinner_x = self.width // 2
            spinner_y = 370
            spinner_radius = 8
            dot_x = spinner_x + int(math.cos(angle) * spinner_radius)
            dot_y = spinner_y + int(math.sin(angle) * spinner_radius)
            pygame.draw.circle(self.screen, (238, 206, 112), (dot_x, dot_y), 3)
            pygame.draw.circle(self.screen, (50, 50, 60), (spinner_x, spinner_y), spinner_radius, 1)
            
            # Subtitle message
            self._draw_text("Please wait while cognitive matrices load.", self.width // 2, 410, (100, 100, 110), center=True)
            
        if self.state == 'combat_state':
            # Draw semi-transparent black overlay (Arena Dim) to dim the overworld
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 150))
            self.screen.blit(overlay, (0, 0))

            # 1. Draw Player (blue) and Enemy (red) and Saif (green, if recruited) in their combat layouts
            # Player (Dodger Blue) animated on the left (with recoil offset if hit)
            player_x_offset = -8 if self.player_recoil_frames > 0 else 0
            if self.player_recoil_frames > 0:
                self.player_recoil_frames -= 1
                
            player_rect = pygame.Rect(int(self.player_combat_current_pos[0]) + player_x_offset, int(self.player_combat_current_pos[1]), self.player.size, self.player.size)
            if self.player_flash_frames > 0:
                pygame.draw.rect(self.screen, (255, 255, 255), player_rect)
                self.player_flash_frames -= 1
            else:
                pygame.draw.rect(self.screen, self.player.color, player_rect)
            
            # Saif (Sea Green) animated on the left next to player (only if recruited)
            if self.saif_recruited:
                saif_x_offset = -8 if self.saif_recoil_frames > 0 else 0
                if self.saif_recoil_frames > 0:
                    self.saif_recoil_frames -= 1
                    
                saif_rect = pygame.Rect(int(self.saif_combat_current_pos[0]) + saif_x_offset, int(self.saif_combat_current_pos[1]), self.player.size, self.player.size)
                if self.saif_flash_frames > 0:
                    pygame.draw.rect(self.screen, (255, 255, 255), saif_rect)
                    self.saif_flash_frames -= 1
                else:
                    pygame.draw.rect(self.screen, (46, 139, 87), saif_rect)
            
            # Enemy (Crimson Red or White Flash) animated/static on the right (hidden when defeated/removed)
            if self.enemy and not self.enemy_defeated_and_removed:
                enemy_rect = pygame.Rect(int(self.enemy_combat_current_pos[0]), int(self.enemy_combat_current_pos[1]), self.enemy.size, self.enemy.size)
                if self.enemy_flash_frames > 0:
                    pygame.draw.rect(self.screen, (255, 255, 255), enemy_rect)
                    self.enemy_flash_frames -= 1
                else:
                    pygame.draw.rect(self.screen, self.enemy.color, enemy_rect)
                
                # Draw floating Enemy HP above the square in upper arena
                enemy_x = int(self.enemy_combat_current_pos[0])
                enemy_y = int(self.enemy_combat_current_pos[1])
                self._draw_text(f"HP: {self.enemy_hp}/100", enemy_x - 10, enemy_y - 40, self.enemy.color)
                pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(enemy_x - 10, enemy_y - 15, 60, 6))
                pygame.draw.rect(self.screen, self.enemy.color, pygame.Rect(enemy_x - 10, enemy_y - 15, int(60 * (self.enemy_hp / 100.0)), 6))
            
            # 2. Draw Bottom Combat Action Menu (Bottom 1/3: Y: 400 to 600)
            if not self.is_sliding and not self.is_combat_ending:
                offset_y = int(self.combat_ui_offset)
                
                # Local offset drawing helpers
                def draw_rect_offset(color, rect, width=0):
                    offset_rect = pygame.Rect(rect.x, rect.y + offset_y, rect.width, rect.height)
                    pygame.draw.rect(self.screen, color, offset_rect, width)

                def draw_line_offset(color, start_pos, end_pos, width=1):
                    offset_start = (start_pos[0], start_pos[1] + offset_y)
                    offset_end = (end_pos[0], end_pos[1] + offset_y)
                    pygame.draw.line(self.screen, color, offset_start, offset_end, width)

                def draw_text_offset(text, x, y, color=(255, 255, 255), center=False):
                    self._draw_text(text, x, y + offset_y, color, center)

                # Fill bottom 200px area with lighter charcoal panel
                draw_rect_offset(self.panel_color, pygame.Rect(0, 400, self.width, 200))
                draw_line_offset(self.grid_color, (0, 400), (self.width, 400), 2)
                
                # Draw vertical box dividers unconditionally
                draw_line_offset(self.grid_color, (250, 400), (250, 600), 2)
                draw_line_offset(self.grid_color, (540, 400), (540, 600), 2)
                
                # COLUMN 1: Action Menu Options (Left Box X: 0 to 250)
                if self.combat_mode == 'item_target':
                    draw_text_offset("Heal who?", 30, 425, (238, 206, 112))
                    draw_text_offset("1: Player", 50, 465, (30, 144, 255))
                    draw_text_offset("2: Saif", 50, 505, (46, 139, 87))
                    draw_text_offset("ESC: Cancel", 30, 550, (150, 150, 150))
                else:
                    for i, option in enumerate(self.menu_options):
                        y_pos = 425 + i * 35
                        if self.combat_mode == 'menu':
                            if i == self.menu_index:
                                draw_text_offset(f"> {option}", 30, y_pos, (30, 144, 255))
                            else:
                                draw_text_offset(option, 50, y_pos, (150, 150, 150))
                        else:
                            # Grayed out because sub-menu is active
                            draw_text_offset(option, 50, y_pos, (70, 70, 75))
                
                # COLUMN 2: Chat Log / Dialogue Box / Submenus (Center Box X: 250 to 540)
                if self.combat_mode == 'talk_input':
                    # Draw label prompt
                    draw_text_offset("Ask Saif:", 270, 415, (200, 200, 210))
                    
                    # Draw multiline text entry box outline
                    input_box_rect = pygame.Rect(270, 445, 250, 90)
                    draw_rect_offset((16, 16, 20), input_box_rect)
                    draw_rect_offset(self.grid_color, input_box_rect, 1)
                    
                    # Wrap input text to multiple lines of max 22 characters per line
                    chars_per_line = 22
                    input_lines = [self.chat_input_text[i:i+chars_per_line] for i in range(0, len(self.chat_input_text), chars_per_line)]
                    if not input_lines:
                        input_lines = [""]
                    
                    # Render wrapped text with flashing caret on the last active character
                    for idx, line in enumerate(input_lines):
                        line_caret = ""
                        if idx == len(input_lines) - 1:
                            line_caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
                        draw_text_offset(line + line_caret, 280, 455 + idx * 25, (255, 255, 255))
                    
                    # Dynamic ESC/ENTER helper text aligned at the bottom
                    draw_text_offset("ESC: Cancel | ENTER: Send", 270, 555, (150, 150, 150))
                    
                elif self.combat_mode == 'talk_response':
                    # Render gold header
                    draw_text_offset("Saif:", 270, 425, (238, 206, 112))
                    
                    # Split and dynamically wrap dialogue to fit Center Box column bounds safely
                    words = self.talk_response_text.split(' ')
                    lines = []
                    current_line = ""
                    for word in words:
                        test_line = current_line + " " + word if current_line else word
                        if len(test_line) < 22:
                            current_line = test_line
                        else:
                            lines.append(current_line)
                            current_line = word
                    if current_line:
                        lines.append(current_line)
                    
                    # Draw dialogue lines
                    for idx, line in enumerate(lines[:4]):
                        draw_text_offset(line, 270, 460 + idx * 28, (245, 245, 245))
                        
                elif self.combat_mode == 'victory':
                    draw_text_offset("VICTORY!", 270, 410, (255, 215, 0))
                    draw_text_offset("Gained 50 EXP", 270, 440, (30, 144, 255))
                    
                    # Render level-ups (stacking dynamically)
                    y_offset = 470
                    if self.levelled_up:
                        draw_text_offset(f"Player Lv. Up! Reached Lv. {self.player_level}", 270, y_offset, (46, 139, 87))
                        y_offset += 25
                    if self.saif_recruited and self.saif_levelled_up:
                        draw_text_offset(f"Saif Lv. Up! Reached Lv. {self.saif_level}", 270, y_offset, (46, 139, 87))
                        y_offset += 25
                    
                    if not self.levelled_up and not (self.saif_recruited and self.saif_levelled_up):
                        draw_text_offset("Press ENTER to continue", 270, 520, (100, 100, 110))
                    else:
                        draw_text_offset("Press ENTER to continue", 270, 550, (100, 100, 110))
                        
                elif self.combat_mode == 'special':
                    draw_text_offset("SPECIAL MOVES", 270, 420, (238, 206, 112))
                    
                    # Check if Combo is available and not on cooldown
                    combo_text = "X-Strike (Combo)"
                    if not self.saif_recruited or self.saif_respect < 70:
                        combo_text += " [Locked: 70+ Respect]"
                        color = (100, 100, 110) # Grayed out
                    elif self.combo_cooldown > 0:
                        combo_text += f" [Cooldown: {self.combo_cooldown} Turn{'s' if self.combo_cooldown > 1 else ''}]"
                        color = (100, 100, 110) # Grayed out
                    else:
                        color = (255, 215, 0) # Gold / Available
                    
                    draw_text_offset(f"> {combo_text}", 270, 460, color)
                    draw_text_offset("ESC: Back | ENTER: Execute", 270, 555, (150, 150, 150))
                    
                elif self.combat_mode == 'item':
                    draw_text_offset("INVENTORY", 270, 420, (238, 206, 112))
                    
                    potions = self.inventory.get("health_potion", 0)
                    item_text = f"Health Potion x{potions}"
                    if potions == 0:
                        color = (100, 100, 110) # Grayed out
                    else:
                        color = (245, 245, 245) # White / Available
                    
                    draw_text_offset(f"> {item_text}", 270, 460, color)
                    draw_text_offset("ESC: Back | ENTER: Use", 270, 555, (150, 150, 150))
                
                elif self.saif_excuse_active:
                    # Render gold header (or crimson for defiance excuse)
                    draw_text_offset("Saif (Refused):", 270, 425, (220, 20, 60))
                    
                    # Split and dynamically wrap dialogue to fit Center Box column bounds safely
                    words = self.saif_excuse_text.split(' ')
                    lines = []
                    current_line = ""
                    for word in words:
                        test_line = current_line + " " + word if current_line else word
                        if len(test_line) < 22:
                            current_line = test_line
                        else:
                            lines.append(current_line)
                            current_line = word
                    if current_line:
                        lines.append(current_line)
                    
                    # Draw dialogue lines
                    for idx, line in enumerate(lines[:4]):
                        draw_text_offset(line, 270, 460 + idx * 28, (245, 245, 245))
                
                # COLUMN 3: Party HP & Respect Stats (Right Box X: 540 to 800)
                # Stats Header
                draw_text_offset("PARTY STATUS", 560, 410, (238, 206, 112))
                
                # Player HP Bar
                draw_text_offset(f"PLAYER LV. {self.player_level} HP: {self.player_hp}/{self.player_max_hp}", 560, 425, (30, 144, 255))
                draw_rect_offset((38, 38, 44), pygame.Rect(560, 445, 200, 6))
                draw_rect_offset((30, 144, 255), pygame.Rect(560, 445, int(200 * (self.player_hp / self.player_max_hp)), 6))
                
                # Player EXP Bar
                draw_text_offset(f"EXP: {self.player_exp}/{self.exp_to_next_level}", 560, 455, (200, 200, 200))
                draw_rect_offset((38, 38, 44), pygame.Rect(560, 475, 200, 4))
                draw_rect_offset((238, 206, 112), pygame.Rect(560, 475, int(200 * (self.player_exp / self.exp_to_next_level)), 4))
                
                # Saif HP and Respect Bars (only if recruited)
                if self.saif_recruited:
                    draw_text_offset(f"SAIF LV. {self.saif_level} HP: {self.saif_hp}/{self.saif_max_hp}", 560, 485, (46, 139, 87))
                    draw_rect_offset((38, 38, 44), pygame.Rect(560, 505, 200, 6))
                    draw_rect_offset((46, 139, 87), pygame.Rect(560, 505, int(200 * (self.saif_hp / self.saif_max_hp)), 6))
                    
                    # Saif EXP Bar
                    draw_text_offset(f"EXP: {self.saif_exp}/{self.saif_exp_to_next_level}", 560, 515, (200, 200, 200))
                    draw_rect_offset((38, 38, 44), pygame.Rect(560, 535, 200, 4))
                    draw_rect_offset((238, 206, 112), pygame.Rect(560, 535, int(200 * (self.saif_exp / self.saif_exp_to_next_level)), 4))
                    
                    # Saif Respect Meter (shows red DEFIANT status if respect < 50)
                    respect_color = (218, 165, 32)
                    respect_label = f"SAIF RESPECT: {self.saif_respect}/100"
                    if self.saif_respect < 50:
                        respect_color = (220, 20, 60) # Flashing/Steady Red
                        respect_label += " [DEFIANT]"
                    
                    draw_text_offset(respect_label, 560, 545, respect_color)
                    draw_rect_offset((38, 38, 44), pygame.Rect(560, 565, 200, 6))
                    draw_rect_offset(respect_color, pygame.Rect(560, 565, int(200 * (self.saif_respect / 100.0)), 6))
                    
                # Draw potions count in Column 3
                draw_text_offset(f"POTIONS: {self.inventory.get('health_potion', 0)}", 560, 580, (238, 206, 112))
            
            # 3. Draw Top State Header Text with Dynamic Turn & Parry Warnings (hidden when ending)
            if not self.is_combat_ending:
                if self.combat_turn == 'player':
                    self._draw_text("PLAYER TURN", self.width // 2, 50, (30, 144, 255), center=True)
                elif self.combat_turn == 'saif':
                    self._draw_text("SAIF TURN", self.width // 2, 50, (46, 139, 87), center=True)
                else:
                    if self.enemy_target == 'player':
                        self._draw_text("ENEMY TURN - PARRY NOW!", self.width // 2, 50, (220, 20, 60), center=True)
                    else:
                        self._draw_text("ENEMY TURN - TARGET: SAIF", self.width // 2, 50, (238, 206, 112), center=True)

            # Render and update floating texts in the combat state
            next_floating_texts = []
            for ft in self.floating_texts:
                color = ft.get("color", (238, 206, 112))
                self._draw_text(ft["text"], ft["x"], ft["y"], color=color, center=True)
                ft["y"] -= 1
                ft["timer"] -= 1
                if ft["timer"] > 0:
                    next_floating_texts.append(ft)
            self.floating_texts = next_floating_texts
        
        # Screen Shake VFX: right before display flip, apply random X/Y offset
        if self.screen_shake_frames > 0:
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)
            temp_surface = self.screen.copy()
            self.screen.fill(self.bg_color)
            self.screen.blit(temp_surface, (offset_x, offset_y))
            self.screen_shake_frames -= 1

        # Update full display surface to screen
        pygame.display.flip()

    def _draw_text(self, text: str, x: int, y: int, color: tuple = (255, 255, 255), center: bool = False):
        """
        Helper utility to render and draw text on the game surface.
        """
        text_surface = self.font.render(text, True, color)
        text_rect = text_surface.get_rect()
        if center:
            text_rect.center = (x, y)
            self.screen.blit(text_surface, text_rect)
        else:
            self.screen.blit(text_surface, (x, y))

    def _draw_prototype_grid(self):
        """
        Draws a subtle 40x40 pixel grid relative to the camera offset
        to give the perfect illusion of an infinite, shifting layout.
        Refined with thin, low-contrast lines to look sleek and modern.
        """
        grid_size = 40
        start_x = -int(self.camera_x % grid_size)
        start_y = -int(self.camera_y % grid_size)
        
        for x in range(start_x, self.width, grid_size):
            pygame.draw.line(self.screen, self.grid_color, (x, 0), (x, self.height), 1)
        for y in range(start_y, self.height, grid_size):
            pygame.draw.line(self.screen, self.grid_color, (0, y), (self.width, y), 1)
