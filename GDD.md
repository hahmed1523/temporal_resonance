# GAME DESIGN DOCUMENT (GDD): Project "Temporal Resonance"

## 1. Core Hook & Perspective
* **Genre:** 2D Time-Travel RPG.
* **Perspective:** Top-down, 2D pixel art (Chrono Trigger style). 
* **Unique Selling Point:** Dynamic LLM-driven party interactions that directly affect combat performance and narrative outcomes, paired with a high-skill live-parry combat loop.

## 2. Character Roster & Archetypes
Each party member has a dominant personality trait that interacts with a shared `respect_meter` (0-100), dictating their combat behavior.

* **The Protagonist (Leo/Maya):** Modern-day human. Uses kinetic weapons (e.g., temporal-infused baseball bat).
* **The Stable Second (Sam/Chloe):** Modern-day human. The reliable anchor and best friend. High base respect.
* **The Flawed Hero (Saif):** Ancient Arabian Desert Guardian. 
    * **Trait:** Over-protective / Traumatized.
    * **Behavior:** At low respect/high stress, panics or skips turns. At high respect, intercepts fatal blows meant for the Protagonist.
* **The Arrogant Berserker (Renzo/Tomoe):** Disgraced Samurai from Feudal Japan.
    * **Trait:** Proud / Battle-Hungry.
    * **Behavior:** At low respect, ignores player commands to auto-attack. At high respect, accepts defensive tactical commands.
* **The Cold Tactician (Zola/Kojo):** Sci-Fi Sniper/Scholar.
    * **Trait:** Purely logical.
    * **Behavior:** Loses respect for suboptimal player choices. Refuses to heal "doomed" party members at low respect.

## 3. Combat Engine
* **Engagement:** Seamless map combat. Enemies are visible on the overworld. Contact initiates the battle UI without loading a separate arena screen.
* **Turn Structure:** Active-Time Battle (ATB). Speed stats dictate how fast the turn meter fills.
* **The "Chat" Command:** A custom combat menu option. The player types a custom message. A local LLM interprets the text against the target party member's personality, dynamically altering the `respect_meter` or granting temporary stat buffs/debuffs.
* **Defensive Mechanics (Live Parry):**
    * No unblockable attacks. Every enemy move can be countered.
    * Enemy attack animations trigger a specific millisecond timing window.
    * Hitting `Spacebar` perfectly inside the window = Perfect Parry (0x damage, restores Energy).
    * Hitting `Spacebar` slightly late = Block (0.5x damage).
    * Hitting `Spacebar` early = Punish State (Player takes 1.5x critical damage).

## 4. Stats & Progression
* **Core Stats:** HP, Energy (stamina for special moves), Speed.
* **Temporal Elements:** 
    * Kinetic (Present/Physical)
    * Thermal (Past/Elemental)
    * Void (Future/Gravity)
* **Leveling System (Hybrid):** 
    * *Milestones:* HP, Base Energy, and Speed strictly increase after major story beats or boss kills (prevents over-leveling).
    * *Tech Points (TP):* Earned via standard combat. Spent in camp to unlock new attacks, upgrade parry windows, or boost starting respect meters.

## 5. The Climax / Awakening Mechanic
* A hidden state check during a late-game boss fight.
* If the boss drops the party to 1 HP, and the `respect_meter` for all three recruited party members is perfectly maxed at 100, an un-skippable "Awakening" event triggers.
* Party HP is restored, music shifts to a triumphant theme, and the Protagonist sprite transforms, unlocking a permanent "Awakened" endgame move set.
* If the respect criteria is not met, the fight simply continues as a brutal, high-stakes survival battle.

## 6. Technical Architecture & File Structure
The project must be modular to maintain a clean context window for future updates that even a junior developer can understand. Do not hardcode narrative or complex state logic into the main game loop. Always use venv and package managers to never update main environments.

* **Folder Structure:** The game will be divided into modular directories: `/engine` (core Pygame logic), `/data` (JSON state and stats), and `/assets` (sprites/audio).
* **State Management:** All player progress, unlocked skills, and `respect_meter` variables must be tracked in an external `game_state.json` file, not hardcoded into character classes.
* **LLM Integration (Context Injection):** The engine will not send full chat histories to the LLM. It will construct lightweight prompts using only the current `game_state`, the specific `NPC_Persona`, and the immediate player input.
* **Map Interactions:** Handled via a tile-based collision system. Interactable objects (chests, NPCs, doors) should trigger modular events based on their object ID, reading from the state manager to determine if they have already been triggered.