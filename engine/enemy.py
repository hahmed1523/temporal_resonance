import pygame

class Enemy:
    """
    Represents an enemy entity in the game world.
    Supports movement velocity, automatic wall collision checking/bouncing, and is_boss flags.
    """
    def __init__(self, x: float, y: float, size: int = 40, color: tuple = (220, 20, 60), vx: float = 0.0, vy: float = 0.0, is_boss: bool = False, enemy_type: str = "goblin_grunt", max_hp: int = 100, base_damage: int = 20):
        """
        Initializes the Enemy entity.
        
        Args:
            x: X coordinate on the screen
            y: Y coordinate on the screen
            size: Width and height of the enemy square
            color: RGB color tuple of the enemy square (default is a vibrant Crimson red)
            vx: Horizontal movement speed (px/sec)
            vy: Vertical movement speed (px/sec)
            is_boss: True if this enemy represents a boss fight trigger
            enemy_type: The string ID of this enemy type
            max_hp: Max health points of this enemy
            base_damage: Attack strength of this enemy
        """
        self.x = float(x)
        self.y = float(y)
        self.size = size
        self.color = color
        self.vx = vx
        self.vy = vy
        self.is_boss = is_boss
        self.enemy_type = enemy_type
        self.max_hp = max_hp
        self.base_damage = base_damage

    def get_rect(self) -> pygame.Rect:
        """
        Returns a pygame.Rect representing the enemy's boundaries for collision detection.
        """
        return pygame.Rect(int(self.x), int(self.y), self.size, self.size)

    def update(self, dt: float, map_grid: list, tile_size: int = 40):
        """
        Updates the enemy's position, checks wall collisions, and bounces on obstacles.
        """
        # Move horizontally
        if self.vx != 0:
            self.x += self.vx * dt
            if self._check_collision(map_grid, tile_size):
                self.x -= self.vx * dt
                self.vx = -self.vx  # Bounce

        # Move vertically
        if self.vy != 0:
            self.y += self.vy * dt
            if self._check_collision(map_grid, tile_size):
                self.y -= self.vy * dt
                self.vy = -self.vy  # Bounce

    def _check_collision(self, map_grid: list, tile_size: int) -> bool:
        """
        Returns True if the enemy overlaps with a wall tile (value 1) or goes outside boundaries.
        """
        rect = self.get_rect()
        
        # Check map bounds
        map_w = len(map_grid[0]) * tile_size
        map_h = len(map_grid) * tile_size
        if rect.left < 0 or rect.right > map_w or rect.top < 0 or rect.bottom > map_h:
            return True
            
        # Check grid tile collisions (walls)
        start_col = int(rect.left // tile_size)
        end_col = int((rect.right - 1) // tile_size)
        start_row = int(rect.top // tile_size)
        end_row = int((rect.bottom - 1) // tile_size)

        for r in range(start_row, end_row + 1):
            for c in range(start_col, end_col + 1):
                if 0 <= r < len(map_grid) and 0 <= c < len(map_grid[0]):
                    if map_grid[r][c] == 1:  # Wall tile
                        return True
        return False

    def draw(self, surface: pygame.Surface, camera_x: float = 0, camera_y: float = 0):
        """
        Draws the enemy square onto the specified Pygame surface relative to camera offsets.
        """
        screen_x = int(self.x - camera_x)
        screen_y = int(self.y - camera_y)
        enemy_rect = pygame.Rect(screen_x, screen_y, self.size, self.size)
        pygame.draw.rect(surface, self.color, enemy_rect)
        
        # Add visual distinction for boss
        if self.is_boss:
            # Draw a gold outline around the boss
            pygame.draw.rect(surface, (238, 206, 112), enemy_rect, 3)
