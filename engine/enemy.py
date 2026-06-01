import pygame

class Enemy:
    """
    Represents a static enemy entity in the game world.
    Currently rendered as a simple crimson red square for the grey-box prototype.
    """
    def __init__(self, x: float, y: float, size: int = 40, color: tuple = (220, 20, 60)):
        """
        Initializes the Enemy entity.
        
        Args:
            x: X coordinate on the screen
            y: Y coordinate on the screen
            size: Width and height of the enemy square
            color: RGB color tuple of the enemy square (default is a vibrant Crimson red)
        """
        self.x = float(x)
        self.y = float(y)
        self.size = size
        self.color = color

    def get_rect(self) -> pygame.Rect:
        """
        Returns a pygame.Rect representing the enemy's boundaries for collision detection.
        """
        return pygame.Rect(int(self.x), int(self.y), self.size, self.size)

    def draw(self, surface: pygame.Surface, camera_x: float = 0, camera_y: float = 0):
        """
        Draws the enemy square onto the specified Pygame surface relative to camera offsets.
        """
        screen_x = int(self.x - camera_x)
        screen_y = int(self.y - camera_y)
        enemy_rect = pygame.Rect(screen_x, screen_y, self.size, self.size)
        pygame.draw.rect(surface, self.color, enemy_rect)
