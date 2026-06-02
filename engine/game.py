import pygame
import sys
import random
import json
import os
import math
from engine.player import Player
from engine.enemy import Enemy
from engine.chest import Chest

from engine.llm_handler import generate_llm_response, save_api_key_to_env
from engine.level_maps import DEFAULT_MAP_GRID, TILE_SIZE, CAMP_MAP_GRID

class Game:
    """
    Main Game engine class.
    Manages the Pygame lifecycle, event handling, updating state, and rendering.
    """
    def __init__(self, width: int = 800, height: int = 600, title: str = "Temporal Resonance", map_grid: list = None):
        """
        Initializes Pygame, sets up the screen, game clock, and game entities.
        """
        pygame.init()
        
        # Screen dimensions and title
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(title)
        
        # Load level map grid
        self.overworld_map_grid = map_grid if map_grid is not None else DEFAULT_MAP_GRID
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
        self._load_game_state()
        
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
        
        # Initialize Game Entities in the middle of the 50x50 world space
        # Tile row 26, col 24 is (960, 1040)
        self.player = Player(960, 1040)
        
        # Static enemy at tile row 26, col 28
        self.enemy = Enemy(1120, 1040)
        
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
        self.player_hp = 100
        self.enemy_hp = 100
        self.saif_hp = 100
        self.combat_turn = 'player'
        self.combat_mode = 'menu'
        self.enemy_combat_current_pos = list(self.enemy_combat_start_pos)
        self.enemy_attack_active = False
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
            "llm_think": self.llm_think
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
        self.current_location = "overworld"
        
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                    self.player_hp = data.get("player_hp", 100)
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
                    self.current_location = data.get("current_location", "overworld")
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
        self.player_hp = 100
        self.enemy_hp = 100
        self.saif_respect = 50
        self.saif_hp = 100
        self.chest_opened = False
        self.saif_recruited = False
        self.chat_history = []
        self.inventory = {"health_potion": 0}
        self.current_location = "overworld"
        
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
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "saif_hp": self.saif_hp,
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
            "current_location": self.current_location
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
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "saif_hp": self.saif_hp,
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
            "player_x": self.player.x,
            "player_y": self.player.y,
            "camera_x": self.camera_x,
            "camera_y": self.camera_y,
            "current_location": self.current_location
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
                    self.player_hp = data.get("player_hp", 100)
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
                    self.player.x = data.get("player_x", 960)
                    self.player.y = data.get("player_y", 1040)
                    self.camera_x = data.get("camera_x", 0.0)
                    self.camera_y = data.get("camera_y", 0.0)
                    self.current_location = data.get("current_location", "overworld")
                
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
                self.player_hp = 100
                self.saif_hp = 100
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
        elif event.key == pygame.K_DOWN:
            self.pause_menu_index = (self.pause_menu_index + 1) % len(self.pause_menu_options)
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
        elif event.key == pygame.K_DOWN:
            self.main_menu_index = (self.main_menu_index + 1) % len(self.main_menu_options)
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            selection = self.main_menu_options[self.main_menu_index]
            
            if selection == "New Game":
                    from main import reset_game_state
                    reset_game_state() # Overwrites game_state.json with defaults
                    self._load_game_state() # Load defaults in memory
                    
                    # Reset physical map cells (close chest)
                    if self.chest_x is not None:
                        c_idx = int(self.chest_x // self.tile_size)
                        r_idx = int(self.chest_y // self.tile_size)
                        self.map_grid[r_idx][c_idx] = 2
                    
                    self.map_grid = self.overworld_map_grid
                    self.current_location = "overworld"
                    self.player.x, self.player.y = 960, 1040 # Reset starting position
                    self.enemy_hp = 100
                    self.player_hp = 100
                    self.saif_hp = 100
                    self._update_camera()
                    self.state = 'exploration_state'
                    print("[System] Started New Game.")
            
            elif selection == "Continue":
                if os.path.exists(self.save_slot_file):
                    self._load_from_save_slot_1()
                    self.state = 'exploration_state'
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
            elif event.key == pygame.K_DOWN:
                self.settings_field_index = (self.settings_field_index + 1) % len(self.settings_fields)
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
        if event.key == pygame.K_ESCAPE and self.combat_mode == 'menu':
            self.is_running = False

        if self.combat_turn == 'player':
            if self.combat_mode == 'menu':
                self._handle_combat_menu(event)
            elif self.combat_mode == 'talk_input':
                self._handle_combat_talk_input(event)
            elif self.combat_mode == 'item_target':
                self._handle_combat_item_target(event)

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
        """Handles menu navigation and action selection during the player's combat turn."""
        # Cycle options with Up / Down arrows
        if event.key == pygame.K_UP:
            self.menu_index = (self.menu_index - 1) % len(self.menu_options)
        elif event.key == pygame.K_DOWN:
            self.menu_index = (self.menu_index + 1) % len(self.menu_options)

        # Enter key triggers option select
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            selected_option = self.menu_options[self.menu_index]

            if selected_option == 'Attack':
                base_dmg = 20
                saif_dmg = 0

                # Coordinated attack from Saif if recruited
                if self.saif_recruited:
                    if self.saif_respect < 50:
                        # 50% chance of disobedience/defiance
                        if random.random() < 0.5:
                            print("[Defiant] Saif refuses your coordinate command and stands idle!")
                        else:
                            print("[Combat] Saif executes a reluctant support strike! (+10 DMG)")
                            saif_dmg = 10
                    else:
                        print("[Combat] Saif executes a coordinated support strike! (+10 DMG)")
                        saif_dmg = 10

                total_dmg = base_dmg + saif_dmg
                self.enemy_hp = max(0, self.enemy_hp - total_dmg)
                self._save_game_state()
                print(f"Attack executed! Total damage: {total_dmg}. Enemy HP: {self.enemy_hp}")

                # Check if enemy defeated
                if self.enemy_hp <= 0:
                    print("Battle Over! Victory achieved.")
                    self._reset_combat_only_state()
                    self.current_location = "overworld"
                    self.state = 'exploration_state'
                    self._knockback_player()
                else:
                    self._start_enemy_turn()

            elif selected_option == 'Talk':
                # Enter Talk Input Mode
                self.combat_mode = 'talk_input'
                self.chat_input_text = ""

            elif selected_option == 'Item':
                potions = self.inventory.get("health_potion", 0)
                if potions > 0:
                    if self.saif_recruited:
                        self.combat_mode = 'item_target'
                        print("[Combat] Item selected. Select target: 1 for Player, 2 for Saif.")
                    else:
                        self.inventory["health_potion"] = potions - 1
                        self.player_hp = min(100, self.player_hp + 50)
                        self._save_game_state()
                        print(f"Used a Health Potion! Restored 50 HP. Player HP: {self.player_hp}")
                        self._start_enemy_turn()
                else:
                    print("No items left!")

            elif selected_option == 'Flee':
                print("Fled from battle!")
                self._knockback_player()
                self.current_location = "overworld"
                self.state = 'exploration_state'

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
                self.player_hp = min(100, self.player_hp + 50)
                self._save_game_state()
                print(f"Used a Health Potion! Restored 50 HP to Player. Player HP: {self.player_hp}")
                self.combat_mode = 'menu'
                self._start_enemy_turn()
        elif event.key in (pygame.K_2, pygame.K_KP2):
            potions = self.inventory.get("health_potion", 0)
            if potions > 0:
                self.inventory["health_potion"] = potions - 1
                self.saif_hp = min(100, self.saif_hp + 50)
                self._save_game_state()
                print(f"Used a Health Potion! Restored 50 HP to Saif. Saif HP: {self.saif_hp}")
                self.combat_mode = 'menu'
                self._start_enemy_turn()


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
        # Allow movement/updates in both exploration and camp states
        if self.state in ('exploration_state', 'camp_state'):
            # Fetch the current state of all keyboard buttons
            keys = pygame.key.get_pressed()
            
            saif_rec_check = self.saif_recruited if self.state == 'exploration_state' else False
            
            # Update player movement
            self.player.handle_input(keys, dt, self.world_width, self.world_height, self.map_grid, saif_rec_check)
            
            # Check collision with overworld enemy only in exploration state
            if self.state == 'exploration_state':
                if self.player.get_collision_rect().colliderect(self.enemy.get_rect()):
                    self.state = 'combat_state'
                    self.current_location = 'combat'
                    self.combat_mode = 'menu'
                    self.combat_turn = 'player'
                    self.menu_index = 0
                    if self.saif_recruited:
                        self.menu_options = ['Attack', 'Talk', 'Item', 'Flee']
                    else:
                        self.menu_options = ['Attack', 'Item', 'Flee']
                    print("Battle Started!")
                
            # Keep camera centered on player
            self._update_camera()
            
        # Peaceful dialogue response resolution timer
        elif self.state == 'dialogue_state' and self.combat_mode == 'talk_response':
            now = pygame.time.get_ticks()
            if now - self.talk_response_start_time >= 4000:
                if self.saif_recruited:
                    # Already recruited! Just return to camp/exploration map
                    if self.active_camp_npc == 'saif':
                        self.state = 'camp_state'
                    else:
                        self.state = 'exploration_state'
                    self.combat_mode = 'menu'
                else:
                    # Not recruited yet! Check if respect meets threshold
                    if self.saif_respect >= 70:
                        print("Saif joined the party!")
                        self.saif_recruited = True
                        self._save_game_state()
                        if self.active_camp_npc == 'saif':
                            self.state = 'camp_state'
                        else:
                            self.state = 'exploration_state'
                        self.combat_mode = 'menu'
                    else:
                        # Keep chatting until respect meets 70
                        self.combat_mode = 'talk_input'
                        self.chat_input_text = ""
                
        # Handle enemy turn sliding animation and timers in combat state
        elif self.state == 'combat_state':
            # Handle response delay timer (2 seconds)
            if self.combat_turn == 'player' and self.combat_mode == 'talk_response':
                now = pygame.time.get_ticks()
                if now - self.talk_response_start_time >= 4000:
                    # Reset player menu mode and trigger Enemy Turn
                    self.combat_mode = 'menu'
                    self._start_enemy_turn()
                    
            elif self.combat_turn == 'enemy' and self.enemy_attack_active:
                now = pygame.time.get_ticks()
                elapsed = now - self.enemy_attack_start_time
                
                # Attacking slide animation (forward then backward) using randomized durations
                # Slide from right (580) to left (190) toward the player/Saif
                start_x = self.enemy_combat_start_pos[0]
                target_x = 190
                target_y = self.player_combat_pos[1] if self.enemy_target == 'player' else self.saif_combat_pos[1]
                
                # Keep Y-axis aligned with the target
                self.enemy_combat_current_pos[1] = target_y
                
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
                    
                    if self.enemy_target == 'player':
                        # Check if player missed parry (didn't parry or failed early/late)
                        if not self.parry_success:
                            if not self.parry_attempted:
                                print("Player took damage!")
                            self.player_hp = max(0, self.player_hp - 20)
                            self._save_game_state()
                    else:
                        # Saif was targeted: parry is skipped
                        print("Saif took damage!")
                        self.saif_hp = max(0, self.saif_hp - 20)
                        self._save_game_state()
                            
                    # Check if either HP hits 0 to end battle
                    if self.player_hp <= 0 or self.saif_hp <= 0:
                        print("Battle Over! Defeat.")
                        self._reset_combat_only_state()
                        self.current_location = "overworld"
                        self.state = 'exploration_state'
                        self._knockback_player()
                    else:
                        # Reset back to player's turn
                        self.combat_turn = 'player'

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
            
        elif self.state in ('exploration_state', 'dialogue_state', 'pause_menu_state', 'camp_state'):
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
                self.enemy.draw(self.screen, self.camera_x, self.camera_y)
                if self.chest_x is not None:
                    c_idx = int(self.chest_x // self.tile_size)
                    r_idx = int(self.chest_y // self.tile_size)
                    if self.map_grid[r_idx][c_idx] == 2:
                        self.chest.draw(self.screen, self.camera_x, self.camera_y)
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
                    
                    # Flickering animation using sine wave
                    import math
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
                    
                    hp_status = f"Player HP: {self.player_hp}/100"
                    if self.saif_recruited:
                        hp_status += f"  |  Saif HP: {self.saif_hp}/100 (Respect: {self.saif_respect}/100)"
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
                    if not self.saif_recruited and self.saif_respect >= 70:
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
            
        elif self.state == 'combat_state':
            # 1. Draw Player (blue) and Enemy (red) and Saif (green, if recruited) in their combat layouts
            # Player (Dodger Blue) static on the left
            player_rect = pygame.Rect(self.player_combat_pos[0], self.player_combat_pos[1], self.player.size, self.player.size)
            pygame.draw.rect(self.screen, self.player.color, player_rect)
            
            # Saif (Sea Green) static on the left next to player (only if recruited)
            if self.saif_recruited:
                saif_rect = pygame.Rect(self.saif_combat_pos[0], self.saif_combat_pos[1], self.player.size, self.player.size)
                pygame.draw.rect(self.screen, (46, 139, 87), saif_rect)
            
            # Enemy (Crimson Red) animated/static on the right
            enemy_rect = pygame.Rect(int(self.enemy_combat_current_pos[0]), int(self.enemy_combat_current_pos[1]), self.enemy.size, self.enemy.size)
            pygame.draw.rect(self.screen, self.enemy.color, enemy_rect)
            
            # Draw floating Crimson Red Enemy HP above the red square in upper arena
            enemy_x = int(self.enemy_combat_current_pos[0])
            enemy_y = int(self.enemy_combat_current_pos[1])
            self._draw_text(f"HP: {self.enemy_hp}/100", enemy_x - 10, enemy_y - 40, (220, 20, 60))
            pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(enemy_x - 10, enemy_y - 15, 60, 6))
            pygame.draw.rect(self.screen, (220, 20, 60), pygame.Rect(enemy_x - 10, enemy_y - 15, int(60 * (self.enemy_hp / 100.0)), 6))
            
            # 2. Draw Bottom Combat Action Menu (Bottom 1/3: Y: 400 to 600)
            # Fill bottom 200px area with lighter charcoal panel
            pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(0, 400, self.width, 200))
            pygame.draw.line(self.screen, self.grid_color, (0, 400), (self.width, 400), 2)
            
            # Draw vertical box dividers unconditionally
            pygame.draw.line(self.screen, self.grid_color, (250, 400), (250, 600), 2)
            pygame.draw.line(self.screen, self.grid_color, (540, 400), (540, 600), 2)
            
            # COLUMN 1: Action Menu Options (Left Box X: 0 to 250)
            if self.combat_mode == 'item_target':
                self._draw_text("Heal who?", 30, 425, (238, 206, 112))
                self._draw_text("1: Player", 50, 465, (30, 144, 255))
                self._draw_text("2: Saif", 50, 505, (46, 139, 87))
                self._draw_text("ESC: Cancel", 30, 550, (150, 150, 150))
            else:
                for i, option in enumerate(self.menu_options):
                    y_pos = 425 + i * 35
                    if self.combat_turn == 'player':
                        if i == self.menu_index:
                            self._draw_text(f"> {option}", 30, y_pos, (30, 144, 255))
                        else:
                            self._draw_text(option, 50, y_pos, (150, 150, 150))
                    else:
                        self._draw_text(option, 50, y_pos, (70, 70, 75))
            
            # COLUMN 2: Chat Log / Dialogue Box (Center Box X: 250 to 540)
            if self.combat_mode == 'talk_input':
                # Draw label prompt
                self._draw_text("Ask Saif:", 270, 415, (200, 200, 210))
                
                # Draw multiline text entry box outline
                input_box_rect = pygame.Rect(270, 445, 250, 90)
                pygame.draw.rect(self.screen, (16, 16, 20), input_box_rect)
                pygame.draw.rect(self.screen, self.grid_color, input_box_rect, 1)
                
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
                    self._draw_text(line + line_caret, 280, 455 + idx * 25, (255, 255, 255))
                
                # Dynamic ESC/ENTER helper text aligned at the bottom
                self._draw_text("ESC: Cancel | ENTER: Send", 270, 555, (150, 150, 150))
                
            elif self.combat_mode == 'talk_response':
                # Render gold header
                self._draw_text("Saif:", 270, 425, (238, 206, 112))
                
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
                    self._draw_text(line, 270, 460 + idx * 28, (245, 245, 245))
            
            # COLUMN 3: Party HP & Respect Stats (Right Box X: 540 to 800)
            # Stats Header
            self._draw_text("PARTY STATUS", 560, 410, (238, 206, 112))
            
            # Player HP Bar
            self._draw_text(f"PLAYER HP: {self.player_hp}/100", 560, 440, (30, 144, 255))
            pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(560, 462, 200, 8))
            pygame.draw.rect(self.screen, (30, 144, 255), pygame.Rect(560, 462, int(200 * (self.player_hp / 100.0)), 8))
            
            # Saif HP and Respect Bars (only if recruited)
            if self.saif_recruited:
                self._draw_text(f"SAIF HP: {self.saif_hp}/100", 560, 490, (46, 139, 87))
                pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(560, 512, 200, 8))
                pygame.draw.rect(self.screen, (46, 139, 87), pygame.Rect(560, 512, int(200 * (self.saif_hp / 100.0)), 8))
                
                # Saif Respect Meter (shows red DEFIANT status if respect < 50)
                respect_color = (218, 165, 32)
                respect_label = f"SAIF RESPECT: {self.saif_respect}/100"
                if self.saif_respect < 50:
                    respect_color = (220, 20, 60) # Flashing/Steady Red
                    respect_label += " [DEFIANT]"
                
                self._draw_text(respect_label, 560, 540, respect_color)
                pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(560, 562, 200, 8))
                pygame.draw.rect(self.screen, respect_color, pygame.Rect(560, 562, int(200 * (self.saif_respect / 100.0)), 8))
                
            # Draw potions count in Column 3
            self._draw_text(f"POTIONS: {self.inventory.get('health_potion', 0)}", 560, 580, (238, 206, 112))
            
            # 3. Draw Top State Header Text with Dynamic Turn & Parry Warnings
            if self.combat_turn == 'player':
                self._draw_text("PLAYER TURN", self.width // 2, 50, (30, 144, 255), center=True)
            else:
                if self.enemy_target == 'player':
                    self._draw_text("ENEMY TURN - PARRY NOW!", self.width // 2, 50, (220, 20, 60), center=True)
                else:
                    self._draw_text("ENEMY TURN - TARGET: SAIF", self.width // 2, 50, (238, 206, 112), center=True)
        
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
