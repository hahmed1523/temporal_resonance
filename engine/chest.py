import pygame

class Chest:
    """
    Represents an interactable Chest entity in the game world.
    Rendered with gold and brown color details to give a premium grey-box feel.
    """
    def __init__(self, x: float, y: float, size: int = 32):
        """
        Initializes the Chest entity.
        
        Args:
            x: World X coordinate
            y: World Y coordinate
            size: Size of the chest box
        """
        self.x = float(x)
        self.y = float(y)
        self.size = size
        
        # Colors for premium pixel look
        self.base_color = (139, 69, 19)      # Rich saddle brown
        self.border_color = (218, 165, 32)   # Dark goldenrod border
        self.lock_color = (238, 206, 112)     # Bright gold lock

    def get_rect(self) -> pygame.Rect:
        """
        Returns a pygame.Rect representing the chest's boundaries for collision.
        """
        return pygame.Rect(int(self.x), int(self.y), self.size, self.size)

    def draw(self, surface: pygame.Surface, camera_x: float = 0, camera_y: float = 0):
        """
        Draws the chest onto the specified Pygame surface relative to the camera offsets.
        """
        screen_x = int(self.x - camera_x)
        screen_y = int(self.y - camera_y)
        
        # Draw base brown box
        chest_rect = pygame.Rect(screen_x, screen_y, self.size, self.size)
        pygame.draw.rect(surface, self.base_color, chest_rect)
        
        # Draw golden border
        pygame.draw.rect(surface, self.border_color, chest_rect, 2)
        
        # Draw a nice gold lock in the middle
        lock_width = 8
        lock_height = 10
        lock_x = screen_x + (self.size - lock_width) // 2
        lock_y = screen_y + (self.size - lock_height) // 2
        pygame.draw.rect(surface, self.lock_color, pygame.Rect(lock_x, lock_y, lock_width, lock_height))
        
        # Draw a tiny black keyhole inside the lock
        keyhole_rect = pygame.Rect(lock_x + 3, lock_y + 3, 2, 4)
        pygame.draw.rect(surface, (16, 16, 20), keyhole_rect)
