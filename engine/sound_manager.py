import os
import wave
import struct
import math
import pygame

class SoundManager:
    """
    Manages loading and playback of background music (BGM) and sound effects (SFX).
    Enforces robust error handling and automatically synthesizes basic placeholder
    WAV tones for missing SFX files.
    """
    def __init__(self):
        self.sounds = {}
        self.current_bgm = None
        
        # Audio track paths
        self.sfx_files = {
            "hit": "assets/audio/hit.wav",
            "parry": "assets/audio/parry.wav",
            "menu_select": "assets/audio/menu_select.wav"
        }
        self.bgm_tracks = {
            "overworld": "assets/audio/overworld_theme.mp3",
            "combat": "assets/audio/battle_theme.mp3",
            "camp": "assets/audio/camp_theme.mp3",
            "title": "assets/audio/title_theme.ogg"
        }
        
        # Ensure the mixer is active before attempting to initialize files
        if pygame.mixer.get_init():
            self._ensure_placeholder_sfx()
            self._load_sfx()
        else:
            print("[SoundManager] Mixer is not initialized. Audio will run in silent mode.")

    def _ensure_placeholder_sfx(self):
        """Checks for existing SFX files and generates synthetic placeholders if missing."""
        for name, path in self.sfx_files.items():
            if not os.path.exists(path):
                print(f"[SoundManager] SFX '{name}' not found at {path}. Generating fallback tone...")
                self._generate_tone(path, name)

    def _generate_tone(self, filepath, sfx_type):
        """
        Synthesizes a short 16-bit PCM mono WAV file using python's standard libraries
        to prevent runtime errors and provide immediate auditory feedback.
        """
        sample_rate = 22050
        data = bytearray()
        
        if sfx_type == "hit":
            # Descending pitch impact sound
            duration = 0.15
            frequency_start = 220.0
            frequency_end = 80.0
            num_samples = int(sample_rate * duration)
            for i in range(num_samples):
                t = i / sample_rate
                # Frequency chirp
                freq = frequency_start + (frequency_end - frequency_start) * (t / duration)
                # Volume envelope (decay)
                volume = 0.5 * (1.0 - t / duration)
                value = int(volume * 32767.0 * math.sin(2.0 * math.pi * freq * t))
                data.extend(struct.pack('<h', value))
                
        elif sfx_type == "parry":
            # Bright chime/tink sound (sum of two sine waves)
            duration = 0.25
            num_samples = int(sample_rate * duration)
            for i in range(num_samples):
                t = i / sample_rate
                volume = 0.4 * (1.0 - t / duration)
                value = int(volume * 32767.0 * (math.sin(2.0 * math.pi * 880.0 * t) + 0.5 * math.sin(2.0 * math.pi * 1320.0 * t)) / 1.5)
                data.extend(struct.pack('<h', value))
                
        elif sfx_type == "menu_select":
            # Short, quick navigation blip
            duration = 0.05
            frequency = 523.25  # C5 note
            num_samples = int(sample_rate * duration)
            for i in range(num_samples):
                t = i / sample_rate
                volume = 0.35 * (1.0 - t / duration)
                value = int(volume * 32767.0 * math.sin(2.0 * math.pi * frequency * t))
                data.extend(struct.pack('<h', value))
                
        else:
            # Simple standard beep
            duration = 0.10
            frequency = 440.0
            num_samples = int(sample_rate * duration)
            for i in range(num_samples):
                t = i / sample_rate
                volume = 0.3 * (1.0 - t / duration)
                value = int(volume * 32767.0 * math.sin(2.0 * math.pi * frequency * t))
                data.extend(struct.pack('<h', value))

        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with wave.open(filepath, 'wb') as wav_file:
                wav_file.setnchannels(1)      # Mono
                wav_file.setsampwidth(2)      # 16-bit
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(data)
            print(f"[SoundManager] Successfully generated placeholder WAV: {filepath}")
        except Exception as e:
            print(f"[SoundManager] Failed to write placeholder WAV {filepath}: {e}")

    def _load_sfx(self):
        """Attempts to load synthesized or custom WAV files into pygame.mixer.Sound."""
        for name, path in self.sfx_files.items():
            try:
                if os.path.exists(path):
                    self.sounds[name] = pygame.mixer.Sound(path)
                    print(f"[SoundManager] Loaded SFX '{name}' successfully.")
                else:
                    self.sounds[name] = None
                    print(f"[SoundManager] SFX '{name}' path not found during load.")
            except Exception as e:
                self.sounds[name] = None
                print(f"[SoundManager] Error loading SFX '{name}' from {path}: {e}")

    def play_sfx(self, name):
        """Plays the mapped sound effect name. Safe if the sound file or mixer is missing."""
        if not pygame.mixer.get_init():
            return
            
        sound = self.sounds.get(name)
        if sound:
            try:
                sound.play()
            except Exception as e:
                print(f"[SoundManager] Error playing SFX '{name}': {e}")
        else:
            # Print fallback to stdout so game feedback is traceable in logs
            print(f"[SoundManager] [SFX Triggered (Silent): {name}]")

    def play_bgm(self, location):
        """
        Transition BGM to the track corresponding to the current location.
        Stops previous BGM and loops new BGM. Safe if file is missing.
        """
        if not pygame.mixer.get_init():
            return
            
        path = self.bgm_tracks.get(location)
        if not path:
            print(f"[SoundManager] No background music mapped for location: '{location}'. Stopping BGM.")
            try:
                pygame.mixer.music.stop()
            except Exception as e:
                print(f"[SoundManager] Error stopping music: {e}")
            self.current_bgm = None
            return
            
        if self.current_bgm == location:
            return  # Already playing this location's theme
            
        print(f"[SoundManager] Switching BGM to location: '{location}'")
        
        # Stop existing playback
        try:
            pygame.mixer.music.stop()
        except Exception as e:
            print(f"[SoundManager] Error stopping current music: {e}")
            
        self.current_bgm = location
        
        # Load and play target track
        try:
            if os.path.exists(path):
                pygame.mixer.music.load(path)
                pygame.mixer.music.play(-1)  # Loop indefinitely
                print(f"[SoundManager] Playing BGM track: {path}")
            else:
                print(f"[SoundManager] BGM track '{path}' not found on disk. Stream will run silently.")
        except Exception as e:
            print(f"[SoundManager] Error loading/playing BGM track {path}: {e}")
