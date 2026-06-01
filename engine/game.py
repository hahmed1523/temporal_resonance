import pygame
import sys
import random
import json
import os
import math
from engine.player import Player
from engine.enemy import Enemy

from engine.llm_handler import generate_llm_response
from engine.level_maps import DEFAULT_MAP_GRID

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
        self.map_grid = map_grid if map_grid is not None else DEFAULT_MAP_GRID
        
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
        self._load_game_state()
        
        # Initialize Game State
        self.state = 'exploration_state'  # States: 'exploration_state', 'combat_state'
        
        # Initialize Game Entities
        # Center the player in the middle of the screen
        start_x = (self.width - 40) // 2
        start_y = (self.height - 40) // 2
        self.player = Player(start_x, start_y)
        
        # Create a static enemy aligned with the grid
        self.enemy = Enemy(520, 280)
        
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
        self.menu_options = ['Attack', 'Talk', 'Flee']
        self.menu_index = 0
        
        # Talk Mode State Variables
        self.combat_mode = 'menu'  # 'menu', 'talk_input', 'talk_response'
        self.chat_input_text = ""
        self.talk_response_text = ""
        self.talk_response_start_time = 0
        
        # Camp Mode State Variables
        self.rest_notification_active = False

    def _load_game_state(self):
        """
        Loads player and enemy HP and respect parameters from the data/game_state.json file.
        Creates default values if the file doesn't exist.
        """
        os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
        
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                    self.player_hp = data.get("player_hp", 100)
                    self.enemy_hp = data.get("enemy_hp", 100)
                    self.saif_respect = data.get("saif_respect", 50)
                    self.saif_hp = data.get("saif_hp", 100)
            except Exception as e:
                print(f"[Error] Failed to load JSON state: {e}. Resetting defaults.")
                self._reset_state_to_default()
        else:
            self._reset_state_to_default()

    def _reset_state_to_default(self):
        """
        Resets active game variables in memory and commits them back to JSON.
        """
        self.player_hp = 100
        self.enemy_hp = 100
        self.saif_respect = 50
        self.saif_hp = 100
        self._save_game_state()

    def _save_game_state(self):
        """
        Saves current memory parameters back to the external data/game_state.json file.
        """
        data = {
            "player_hp": self.player_hp,
            "enemy_hp": self.enemy_hp,
            "saif_respect": self.saif_respect,
            "saif_hp": self.saif_hp
        }
        try:
            with open(self.state_file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Error] Failed to save JSON state: {e}")

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
            self.player.clamp_to_screen(self.width, self.height)
            if hasattr(self, 'map_grid') and self.player.check_wall_collisions(self.map_grid):
                # Collision: Revert horizontal step
                self.player.x -= dx * step_size
                
            # Try vertical step
            self.player.y += dy * step_size
            self.player.clamp_to_screen(self.width, self.height)
            if hasattr(self, 'map_grid') and self.player.check_wall_collisions(self.map_grid):
                # Collision: Revert vertical step
                self.player.y -= dy * step_size
                
        self._save_game_state()

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
        Processes standard game loop events such as window closing or ESC key pressing.
        """
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.is_running = False
            elif event.type == pygame.KEYDOWN:
                # Camp State Controls
                if self.state == 'camp_state':
                    if event.key == pygame.K_ESCAPE:
                        self.state = 'exploration_state'
                    elif event.key == pygame.K_r:
                        self.player_hp = 100
                        self.saif_hp = 100
                        self.rest_notification_active = True
                        self._save_game_state()
                        print("Party Rested!")
                
                # Exploration State Controls
                elif self.state == 'exploration_state':
                    if event.key == pygame.K_ESCAPE:
                        self.is_running = False
                    elif event.key == pygame.K_c:
                        self.state = 'camp_state'
                        self.rest_notification_active = False
                        self._load_game_state()
                
                # Combat State Controls
                elif self.state == 'combat_state':
                    if event.key == pygame.K_ESCAPE:
                        self.is_running = False
                    if self.combat_turn == 'player':
                        if self.combat_mode == 'menu':
                            # Cycle options with Up / Down arrows
                            if event.key == pygame.K_UP:
                                self.menu_index = (self.menu_index - 1) % len(self.menu_options)
                            elif event.key == pygame.K_DOWN:
                                self.menu_index = (self.menu_index + 1) % len(self.menu_options)
                            
                            # Enter key triggers option select
                            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                                selected_option = self.menu_options[self.menu_index]
                                
                                if selected_option == 'Attack':
                                    # Deduct 20 HP from enemy
                                    self.enemy_hp = max(0, self.enemy_hp - 20)
                                    self._save_game_state()
                                    print(f"Player attacked! Enemy HP: {self.enemy_hp}")
                                    
                                    # Check if enemy defeated
                                    if self.enemy_hp <= 0:
                                        print("Battle Over!")
                                        self._reset_state_to_default()
                                        self.state = 'exploration_state'
                                        self._knockback_player()
                                    else:
                                        # Trigger enemy attack lunge
                                        self.combat_turn = 'enemy'
                                        self.enemy_attack_active = True
                                        self.enemy_attack_start_time = pygame.time.get_ticks()
                                        self.parry_attempted = False
                                        self.parry_success = False
                                        
                                        # Randomly pick target: 'player' or 'saif'
                                        self.enemy_target = random.choice(['player', 'saif'])
                                        target_y = self.player_combat_pos[1] if self.enemy_target == 'player' else self.saif_combat_pos[1]
                                        self.enemy_combat_current_pos = [self.enemy_combat_start_pos[0], target_y]
                                        
                                        # Randomize forward attack lunge duration (300ms to 750ms)
                                        self.forward_duration = random.randint(300, 750)
                                        self.total_duration = self.forward_duration * 2
                                        
                                        # Scale parry window centered on impact
                                        self.parry_window_start = self.forward_duration - 100
                                        self.parry_window_end = self.forward_duration + 20
                                        print(f"[Debug System] Enemy targets: {self.enemy_target.upper()}. Attack Speed Picked: {self.forward_duration}ms. Parry range: {self.parry_window_start} - {self.parry_window_end}")
                                
                                elif selected_option == 'Talk':
                                    # Enter Talk Input Mode
                                    self.combat_mode = 'talk_input'
                                    self.chat_input_text = ""
                                    
                                elif selected_option == 'Flee':
                                    print("Fled from battle!")
                                    self._knockback_player()
                                    self.state = 'exploration_state'
                                    
                        elif self.combat_mode == 'talk_input':
                            if event.key == pygame.K_ESCAPE:
                                # Cancel and return to menu
                                self.combat_mode = 'menu'
                            elif event.key == pygame.K_BACKSPACE:
                                # Delete last character
                                self.chat_input_text = self.chat_input_text[:-1]
                            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                                # Submit chat input
                                if self.chat_input_text.strip():
                                    res_dict = generate_llm_response(self.chat_input_text, self.saif_respect)
                                    dialogue = res_dict.get("dialogue", "Saif remains silent.")
                                    change = res_dict.get("respect_change", 0)
                                    
                                    # Apply respect change and save
                                    self.saif_respect = max(0, min(100, self.saif_respect + change))
                                    self._save_game_state()
                                    
                                    self.talk_response_text = dialogue
                                    self.talk_response_start_time = pygame.time.get_ticks()
                                    self.combat_mode = 'talk_response'
                            else:
                                # Append key characters (only standard printable text, max 18 characters to fit column)
                                if event.unicode and ord(event.unicode) >= 32 and len(self.chat_input_text) < 18:
                                    self.chat_input_text += event.unicode
                    
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

    def _update(self, dt: float):
        """
        Updates the state of all active game entities.
        """
        # Only allow movement/updates when in exploration state
        if self.state == 'exploration_state':
            # Fetch the current state of all keyboard buttons
            keys = pygame.key.get_pressed()
            
            # Update the player entity using the key states, delta time, and level map
            self.player.handle_input(keys, dt, self.width, self.height, self.map_grid)
            
            # Check collision with the static enemy
            if self.player.get_collision_rect().colliderect(self.enemy.get_rect()):
                self.state = 'combat_state'
                print("Battle Started!")
                
        # Handle enemy turn sliding animation and timers in combat state
        elif self.state == 'combat_state':
            # Handle response delay timer (2 seconds)
            if self.combat_turn == 'player' and self.combat_mode == 'talk_response':
                now = pygame.time.get_ticks()
                if now - self.talk_response_start_time >= 4000:
                    # Reset player menu mode and trigger Enemy Turn
                    self.combat_mode = 'menu'
                    self.combat_turn = 'enemy'
                    self.enemy_attack_active = True
                    self.enemy_attack_start_time = pygame.time.get_ticks()
                    self.parry_attempted = False
                    self.parry_success = False
                    
                    # Randomly pick target: 'player' or 'saif'
                    self.enemy_target = random.choice(['player', 'saif'])
                    target_y = self.player_combat_pos[1] if self.enemy_target == 'player' else self.saif_combat_pos[1]
                    self.enemy_combat_current_pos = [self.enemy_combat_start_pos[0], target_y]
                    
                    # Randomize forward attack lunge duration (300ms to 750ms)
                    self.forward_duration = random.randint(300, 750)
                    self.total_duration = self.forward_duration * 2
                    
                    # Scale parry window centered on impact
                    self.parry_window_start = self.forward_duration - 100
                    self.parry_window_end = self.forward_duration + 20
                    print(f"[Debug System] Enemy targets: {self.enemy_target.upper()}. Attack Speed Picked: {self.forward_duration}ms. Parry range: {self.parry_window_start} - {self.parry_window_end}")
                    
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
                        print("Battle Over!")
                        self._reset_state_to_default()
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
        
        if self.state == 'exploration_state':
            # Render solid grey walls from map grid first
            if hasattr(self, 'map_grid') and self.map_grid:
                tile_size = 40
                wall_color = (60, 60, 68)      # Modern slate grey
                border_color = (48, 48, 54)    # Darker grey for tile borders
                for r_idx, row in enumerate(self.map_grid):
                    for c_idx, cell in enumerate(row):
                        if cell == 1:
                            wall_rect = pygame.Rect(c_idx * tile_size, r_idx * tile_size, tile_size, tile_size)
                            pygame.draw.rect(self.screen, wall_color, wall_rect)
                            pygame.draw.rect(self.screen, border_color, wall_rect, 1)
                            
            # Draw a modern, subtle grid for a professional "grey-box" prototype look
            self._draw_prototype_grid()
            
            # Render game entities
            self.enemy.draw(self.screen)
            self.player.draw(self.screen)
            
        elif self.state == 'camp_state':
            # Draw a sleek camp screen UI
            # 1. Clean visual border box
            pygame.draw.rect(self.screen, self.panel_color, pygame.Rect(50, 50, 700, 500))
            pygame.draw.rect(self.screen, self.grid_color, pygame.Rect(50, 50, 700, 500), 2)
            
            # 2. Header
            self._draw_text("CAMPFIRE COGNIZANCE", 400, 90, (238, 206, 112), center=True)
            pygame.draw.line(self.screen, self.grid_color, (100, 125), (700, 125), 1)
            
            # 3. Party Status Checklist
            self._draw_text("PARTY STATUS:", 100, 160, (200, 200, 210))
            
            self._draw_text(f"- Player HP: {self.player_hp}/100", 120, 210, (30, 144, 255))
            self._draw_text(f"- Saif (Traumatized Guardian):", 120, 260, (238, 206, 112))
            self._draw_text(f"  HP: {self.saif_hp}/100 | Respect Meter: {self.saif_respect}/100", 120, 290, (180, 180, 185))
            
            self._draw_text(f"- Target Enemy HP: {self.enemy_hp}/100", 120, 340, (220, 20, 60))
            
            pygame.draw.line(self.screen, self.grid_color, (100, 400), (700, 400), 1)
            
            # 4. Commands Box
            self._draw_text("Press R to Rest (Restores HP to 100)", 400, 440, (255, 255, 255), center=True)
            self._draw_text("Press ESC to return to the map", 400, 480, (150, 150, 150), center=True)
            
            # 5. Rest Confirmation notification
            if self.rest_notification_active:
                self._draw_text("Party Rested! HP Restored.", 400, 520, (46, 139, 87), center=True)
            
        elif self.state == 'combat_state':
            # 1. Draw Player (blue) and Enemy (red) and Saif (green) in their combat layouts
            # Player (Dodger Blue) static on the left
            player_rect = pygame.Rect(self.player_combat_pos[0], self.player_combat_pos[1], self.player.size, self.player.size)
            pygame.draw.rect(self.screen, self.player.color, player_rect)
            
            # Saif (Sea Green) static on the left next to player
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
                self._draw_text("Ask Saif:", 270, 425, (200, 200, 210))
                
                # Draw text entry box outline
                input_box_rect = pygame.Rect(270, 460, 250, 36)
                pygame.draw.rect(self.screen, (16, 16, 20), input_box_rect)
                pygame.draw.rect(self.screen, self.grid_color, input_box_rect, 1)
                
                # Render typed text with a flashing text cursor (limited to fit width)
                caret = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
                self._draw_text(self.chat_input_text + caret, 280, 466, (255, 255, 255))
                
                # ESC helper text
                self._draw_text("ESC: Cancel", 270, 515, (150, 150, 150))
                
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
            
            # Saif HP Bar
            self._draw_text(f"SAIF HP: {self.saif_hp}/100", 560, 490, (46, 139, 87))
            pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(560, 512, 200, 8))
            pygame.draw.rect(self.screen, (46, 139, 87), pygame.Rect(560, 512, int(200 * (self.saif_hp / 100.0)), 8))
            
            # Saif Respect Bar
            self._draw_text(f"SAIF RESPECT: {self.saif_respect}/100", 560, 540, (218, 165, 32))
            pygame.draw.rect(self.screen, (38, 38, 44), pygame.Rect(560, 562, 200, 8))
            pygame.draw.rect(self.screen, (218, 165, 32), pygame.Rect(560, 562, int(200 * (self.saif_respect / 100.0)), 8))
                
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
        Draws a subtle 40x40 pixel grid to give context for movement and placement.
        Refined with thin, low-contrast lines to look sleek and modern.
        """
        grid_size = 40
        for x in range(0, self.width, grid_size):
            pygame.draw.line(self.screen, self.grid_color, (x, 0), (x, self.height), 1)
        for y in range(0, self.height, grid_size):
            pygame.draw.line(self.screen, self.grid_color, (0, y), (self.width, y), 1)
