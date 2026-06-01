import pygame
import math

from engine.level_maps import TILE_SIZE

class Player:
    """
    Represents the player entity in the game world.
    Currently rendered as a simple blue square for the grey-box prototype.
    """
    def __init__(self, x: float, y: float, size: int = 32, speed: float = 300.0, color: tuple = (30, 144, 255), shrink: int = 0):
        """
        Initializes the Player entity.
        
        Args:
            x: Initial X coordinate (float for smooth sub-pixel delta movement)
            y: Initial Y coordinate
            size: Width and height of the player square
            speed: Movement speed in pixels per second (delta-time scaled)
            color: RGB color tuple of the player square (default is a vibrant Dodger Blue)
            shrink: Bounding box padding for tighter navigation (0 for perfect visual-physical match)
        """
        self.x = float(x)
        self.y = float(y)
        self.size = size
        self.speed = speed
        self.color = color
        self.shrink = shrink

    def handle_input(self, keys: pygame.key.ScancodeWrapper, dt: float, screen_width: int, screen_height: int, map_grid: list = None, saif_recruited: bool = False):
        """
        Processes keyboard inputs and moves the player smoothly using delta time.
        Implements diagonal movement speed normalization and axis-discrete sliding wall collisions.
        
        Args:
            keys: The pygame key pressed state list
            dt: Delta time in seconds since the last frame
            screen_width: The width of the game screen (for clamping)
            screen_height: The height of the game screen (for clamping)
            map_grid: The 2D level matrix containing wall blocks
            saif_recruited: Boolean indicating if Saif has been recruited to the party
        """
        # Determine movement vector from arrow keys
        dx = 0.0
        dy = 0.0
        
        if keys[pygame.K_LEFT]:
            dx -= 1.0
        if keys[pygame.K_RIGHT]:
            dx += 1.0
        if keys[pygame.K_UP]:
            dy -= 1.0
        if keys[pygame.K_DOWN]:
            dy += 1.0
            
        # Normalize the movement vector if moving diagonally
        if dx != 0.0 or dy != 0.0:
            length = math.sqrt(dx * dx + dy * dy)
            dx /= length
            dy /= length
            
            shrink = self.shrink
            tile_size = TILE_SIZE
            
            # 1. Apply horizontal speed and delta-time scaling
            if dx != 0.0:
                self.x += dx * self.speed * dt
                self.clamp_to_screen(screen_width, screen_height)
                if map_grid:
                    collision_rect = self.get_collision_rect()
                    for r_idx, row in enumerate(map_grid):
                        for c_idx, cell in enumerate(row):
                            if cell == 1 or (cell == 3 and not saif_recruited):
                                wall_rect = pygame.Rect(c_idx * tile_size, r_idx * tile_size, tile_size, tile_size)
                                if collision_rect.colliderect(wall_rect):
                                    # Horizontal collision: Push player flush against the wall boundary
                                    if dx > 0:  # Moving right
                                        self.x = float(wall_rect.left - self.size + shrink)
                                    elif dx < 0:  # Moving left
                                        self.x = float(wall_rect.right - shrink)
                                    collision_rect = self.get_collision_rect()
            
            # 2. Apply vertical speed and delta-time scaling
            if dy != 0.0:
                self.y += dy * self.speed * dt
                self.clamp_to_screen(screen_width, screen_height)
                if map_grid:
                    collision_rect = self.get_collision_rect()
                    for r_idx, row in enumerate(map_grid):
                        for c_idx, cell in enumerate(row):
                            if cell == 1 or (cell == 3 and not saif_recruited):
                                wall_rect = pygame.Rect(c_idx * tile_size, r_idx * tile_size, tile_size, tile_size)
                                if collision_rect.colliderect(wall_rect):
                                    # Vertical collision: Push player flush against the wall boundary
                                    if dy > 0:  # Moving down
                                        self.y = float(wall_rect.top - self.size + shrink)
                                    elif dy < 0:  # Moving up
                                        self.y = float(wall_rect.bottom - shrink)
                                    collision_rect = self.get_collision_rect()

    def get_collision_rect(self) -> pygame.Rect:
        """
        Returns a slightly smaller bounding box to allow smooth navigation through tight corridors.
        """
        shrink = self.shrink
        return pygame.Rect(int(self.x) + shrink, int(self.y) + shrink, self.size - shrink * 2, self.size - shrink * 2)

    def check_wall_collisions(self, map_grid: list, saif_recruited: bool = False) -> bool:
        """
        Checks if the player's collision hitbox overlaps with any solid wall block (1) or unrecruited Saif (3).
        
        Args:
            map_grid: The 2D level layout list
            saif_recruited: Boolean indicating if Saif has been recruited to the party
            
        Returns:
            True if player collision Rect overlaps a solid tile, False otherwise.
        """
        collision_rect = self.get_collision_rect()
        tile_size = TILE_SIZE
        
        for r_idx, row in enumerate(map_grid):
            for c_idx, cell in enumerate(row):
                if cell == 1 or (cell == 3 and not saif_recruited):
                    wall_rect = pygame.Rect(c_idx * tile_size, r_idx * tile_size, tile_size, tile_size)
                    if collision_rect.colliderect(wall_rect):
                        return True
        return False

    def clamp_to_screen(self, screen_width: int, screen_height: int):
        """
        Restricts the player's position to keep them entirely within screen bounds.
        """
        if self.x < 0:
            self.x = 0.0
        elif self.x > screen_width - self.size:
            self.x = float(screen_width - self.size)
            
        if self.y < 0:
            self.y = 0.0
        elif self.y > screen_height - self.size:
            self.y = float(screen_height - self.size)

    def get_rect(self) -> pygame.Rect:
        """
        Returns a pygame.Rect representing the player's boundaries for collision detection.
        """
        return pygame.Rect(int(self.x), int(self.y), self.size, self.size)

    def draw(self, surface: pygame.Surface, camera_x: float = 0, camera_y: float = 0):
        """
        Draws the player square onto the specified Pygame surface relative to camera offsets.
        """
        screen_x = int(self.x - camera_x)
        screen_y = int(self.y - camera_y)
        player_rect = pygame.Rect(screen_x, screen_y, self.size, self.size)
        pygame.draw.rect(surface, self.color, player_rect)
