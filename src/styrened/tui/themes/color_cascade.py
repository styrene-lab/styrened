"""Color cascade system for deriving theme colors from a root phosphex color.

All theme colors are calculated algorithmically from a single configurable
phosphex (phosphor) color, enabling easy theming while maintaining visual consistency.

Presets are named after Warhammer 40k Forge Worlds, each with a signature
phosphor color reflecting their industrial character.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from textual.theme import Theme


class ForgeWorldPreset(NamedTuple):
    """A forge world phosphex color preset."""

    name: str
    phosphex: str
    description: str


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB values to hex color string."""
    return f"#{r:02x}{g:02x}{b:02x}"


def clamp(value: int, min_val: int = 0, max_val: int = 255) -> int:
    """Clamp a value to valid RGB range."""
    return max(min_val, min(max_val, value))


def scale_color(hex_color: str, factor: float) -> str:
    """Scale a color's brightness by a factor (0.0 to 2.0+)."""
    r, g, b = hex_to_rgb(hex_color)
    return rgb_to_hex(
        clamp(int(r * factor)),
        clamp(int(g * factor)),
        clamp(int(b * factor)),
    )


def create_tinted_dark(hex_color: str, base_brightness: int, tint_factor: float) -> str:
    """Create a near-black color tinted toward the phosphex color.

    Args:
        hex_color: Source phosphex color for tinting direction
        base_brightness: Base RGB value (0-255)
        tint_factor: How much phosphex influence to add (0.0-1.0)
    """
    r, g, b = hex_to_rgb(hex_color)
    # Find dominant channel and apply subtle tint
    max_channel = max(r, g, b) or 1
    r_ratio = r / max_channel
    g_ratio = g / max_channel
    b_ratio = b / max_channel

    # Apply tint: base brightness + subtle color influence
    return rgb_to_hex(
        clamp(int(base_brightness * (1 + (r_ratio - 0.5) * tint_factor))),
        clamp(int(base_brightness * (1 + (g_ratio - 0.5) * tint_factor))),
        clamp(int(base_brightness * (1 + (b_ratio - 0.5) * tint_factor))),
    )


# =============================================================================
# FORGE WORLD PRESETS
# 32 phosphex colors named after Warhammer 40k Forge Worlds
# =============================================================================

FORGE_WORLD_PRESETS: dict[str, ForgeWorldPreset] = {
    # === GREENS (Imperial standard phosphor) ===
    "mars": ForgeWorldPreset(
        "Mars Pattern",
        "#39ff14",
        "Electric green - the sacred color of the Omnissiah's first forge",
    ),
    "terra": ForgeWorldPreset(
        "Holy Terra",
        "#00ff00",
        "Pure green - the blessed light of the Throneworld's ancient cogitators",
    ),
    "graia": ForgeWorldPreset(
        "Graia Pattern", "#32cd32", "Lime green - stubborn and unyielding like Graia's warriors"
    ),
    "incaladion": ForgeWorldPreset(
        "Incaladion Pattern", "#7fff00", "Chartreuse - the verdant glow of Incaladion's bio-forges"
    ),
    # === AMBERS/ORANGES (Ryza plasma specialist) ===
    "ryza": ForgeWorldPreset(
        "Ryza Pattern", "#ff8c00", "Dark orange - the plasma-burn glow of Ryza's weapon forges"
    ),
    "phaeton": ForgeWorldPreset(
        "Phaeton Pattern", "#ffb000", "Amber - classical CRT phosphor of Phaeton's archives"
    ),
    "tigrus": ForgeWorldPreset(
        "Tigrus Pattern", "#ffa500", "Orange - fierce like the war machines of Tigrus"
    ),
    "estaban": ForgeWorldPreset(
        "Estaban III Pattern", "#ff6600", "Flame orange - the forge-fires of Estaban III"
    ),
    # === REDS (Traitor and blood-forges) ===
    "sarum": ForgeWorldPreset(
        "Sarum Pattern", "#ff3333", "Crimson - the blood-red glow of Sarum's weapon shrines"
    ),
    "cyclothrathe": ForgeWorldPreset(
        "Cyclothrathe Pattern", "#dc143c", "Crimson - the dark forges touched by the warp"
    ),
    "samech": ForgeWorldPreset(
        "Samech Pattern", "#ff4444", "Scarlet - the forbidden light of Samech's dark archives"
    ),
    "xana": ForgeWorldPreset(
        "Xana II Pattern", "#cc0000", "Blood red - the traitor forge's corrupted phosphor"
    ),
    # === BLUES (Stygies stealth specialists) ===
    "stygies": ForgeWorldPreset(
        "Stygies VIII Pattern", "#00bfff", "Deep sky blue - the covert glow of Stygies' xenos-tech"
    ),
    "deimos": ForgeWorldPreset(
        "Deimos Pattern", "#4169e1", "Royal blue - the Grey Knights' forge moon"
    ),
    "hydraphur": ForgeWorldPreset(
        "Hydraphur Pattern", "#1e90ff", "Dodger blue - the naval yards of Hydraphur"
    ),
    "mezoa": ForgeWorldPreset(
        "Mezoa Pattern", "#00ced1", "Dark turquoise - Mezoa's void-walker technology"
    ),
    # === CYANS/TEALS ===
    "agripinaa": ForgeWorldPreset(
        "Agripinaa Pattern", "#00ffff", "Cyan - the Eye of Terror's threshold forge"
    ),
    "triplex_phall": ForgeWorldPreset(
        "Triplex Phall Pattern", "#20b2aa", "Light sea green - the isolated eastern forge"
    ),
    "kiavahr": ForgeWorldPreset(
        "Kiavahr Pattern", "#40e0d0", "Turquoise - Corax's forge homeworld"
    ),
    "konor": ForgeWorldPreset(
        "Konor Pattern", "#48d1cc", "Medium turquoise - the Ultramar sector forge"
    ),
    # === PURPLES (Lucius and specialty forges) ===
    "lucius": ForgeWorldPreset(
        "Lucius Pattern", "#9370db", "Medium purple - Lucius' jealously guarded technologies"
    ),
    "voss": ForgeWorldPreset(
        "Voss Prime Pattern", "#8a2be2", "Blue violet - the Legio Cybernetica masters"
    ),
    "zhao_arkhad": ForgeWorldPreset(
        "Zhao-Arkhad Pattern", "#9932cc", "Dark orchid - the Death World forge's resilience"
    ),
    "moirae": ForgeWorldPreset(
        "Moirae Pattern", "#ba55d3", "Medium orchid - the schismatic forge's forbidden lore"
    ),
    # === PINKS/MAGENTAS ===
    "accatran": ForgeWorldPreset(
        "Accatran Pattern", "#ff69b4", "Hot pink - the laser specialists' distinct glow"
    ),
    "urdesh": ForgeWorldPreset(
        "Urdesh Pattern", "#ff1493", "Deep pink - Sabbat Worlds forge resilience"
    ),
    # === WHITES/GRAYS (Metalica) ===
    "metalica": ForgeWorldPreset(
        "Metalica Pattern", "#e0e0e0", "White phosphor - Metalica's relentless advance"
    ),
    "vostroya": ForgeWorldPreset(
        "Vostroya Pattern", "#c0c0c0", "Silver - the ancestral forges of Vostroya"
    ),
    "gantz": ForgeWorldPreset(
        "Gantz Pattern", "#a8a8a8", "Gray - the industrial monotone of Gantz"
    ),
    # === GOLDS/YELLOWS ===
    "gryphonne": ForgeWorldPreset(
        "Gryphonne IV Pattern", "#ffd700", "Gold - the lost splendor of Gryphonne IV"
    ),
    "shenlong": ForgeWorldPreset(
        "Shenlong Pattern", "#ffff00", "Yellow - the eastern forge's radiant output"
    ),
    "vanaheim": ForgeWorldPreset(
        "Vanaheim Pattern", "#f0e68c", "Khaki - the ice-world forge's warm glow"
    ),
}


# Ordered list for UI selection (grouped by color family)
FORGE_WORLD_ORDER = [
    # Greens
    "mars",
    "terra",
    "graia",
    "incaladion",
    # Ambers/Oranges
    "ryza",
    "phaeton",
    "tigrus",
    "estaban",
    # Reds
    "sarum",
    "cyclothrathe",
    "samech",
    "xana",
    # Blues
    "stygies",
    "deimos",
    "hydraphur",
    "mezoa",
    # Cyans
    "agripinaa",
    "triplex_phall",
    "kiavahr",
    "konor",
    # Purples
    "lucius",
    "voss",
    "zhao_arkhad",
    "moirae",
    # Pinks
    "accatran",
    "urdesh",
    # Whites/Grays
    "metalica",
    "vostroya",
    "gantz",
    # Golds/Yellows
    "gryphonne",
    "shenlong",
    "vanaheim",
]


def get_preset(name: str) -> ForgeWorldPreset | None:
    """Get a forge world preset by key name."""
    return FORGE_WORLD_PRESETS.get(name.lower().replace("-", "_").replace(" ", "_"))


def list_presets() -> list[tuple[str, ForgeWorldPreset | None]]:
    """List all presets in display order.

    The styrene brand theme appears first, followed by forge world presets.
    """
    from styrened.tui.themes.styrene_brand import STYRENE_THEME_KEY

    result: list[tuple[str, ForgeWorldPreset | None]] = [
        (STYRENE_THEME_KEY, None),
    ]
    result.extend((key, FORGE_WORLD_PRESETS[key]) for key in FORGE_WORLD_ORDER)
    return result


# =============================================================================
# COLOR CASCADE
# =============================================================================


@dataclass
class ColorCascade:
    """Derived color palette from a single phosphex (phosphor) color.

    All colors are calculated from the phosphex using deterministic
    algorithms, ensuring visual consistency across the theme.

    The phosphex is the root color from which all others derive - named
    after the Mechanicum's sacred Phosphex weapons.
    """

    # The source color - all others derive from this
    phosphex: str = "#39ff14"  # Electric green (Mars Pattern default)

    # Optional preset name for reference
    preset_name: str = field(default="Mars Pattern")

    def __post_init__(self) -> None:
        """Calculate all derived colors from phosphex."""
        self._calculate_palette()

    def _calculate_palette(self) -> None:
        """Derive the complete color palette from phosphex."""
        # === Phosphor Shades (text brightness levels) ===
        # Bright: full phosphex color
        self.bright = self.phosphex

        # Medium: 60% brightness
        self.medium = scale_color(self.phosphex, 0.6)

        # Dim: 35% brightness
        self.dim = scale_color(self.phosphex, 0.35)

        # Dark: 20% brightness (barely visible)
        self.dark = scale_color(self.phosphex, 0.20)

        # === Background Colors ===
        # Screen background: near-black with subtle phosphex tint
        self.bg_screen = create_tinted_dark(self.phosphex, 10, 0.3)

        # Panel background: slightly brighter with phosphex tint
        self.bg_panel = create_tinted_dark(self.phosphex, 12, 0.4)

        # Panel elevated: for HighlightedPanel (more visible)
        self.bg_panel_elevated = create_tinted_dark(self.phosphex, 15, 0.4)

        # Hover/focus background
        self.bg_hover = create_tinted_dark(self.phosphex, 18, 0.45)

        # === Border Colors ===
        # Border dim: barely visible borders (phosphex tinted)
        self.border_dim = create_tinted_dark(self.phosphex, 26, 0.5)

        # Border medium: standard borders
        self.border_medium = create_tinted_dark(self.phosphex, 42, 0.5)

        # Border bright: focused/highlighted borders (uses dim phosphor)
        self.border_bright = self.dim

        # Corner highlight: bright accent for panel corners
        self.corner_highlight = self.bright

        # === Status Colors ===
        # All colors derive from phosphex - visual differentiation comes from
        # symbols (●○◐◓) and text-style, NOT from color hue.
        # Status colors use varying brightness levels of the phosphex.
        self.status_online = self.bright  # Brightest = active
        self.status_offline = self.dark  # Darkest = inactive
        self.status_pending = self.medium  # Medium = transitioning
        self.status_scanning = self.dim  # Dim = processing
        self.status_info = self.medium  # Medium for general info

        # === Semantic Colors (for buttons, alerts) ===
        # All derive from phosphex - differentiation comes from shade patterns
        # (▓▒░) and text-style (bold underline, bold italic, reverse), NOT hue.
        self.color_success = self.bright  # Brightest = positive outcome
        self.color_warning = self.medium  # Medium = caution
        self.color_danger = self.dim  # Dim + reverse style = alarming
        self.color_info = self.medium  # Medium for informational

    @classmethod
    def from_textual_theme(cls, theme: "Theme") -> "ColorCascade":
        """Create a ColorCascade from an active Textual Theme.

        Uses the theme's accent color as the phosphex root, then overrides
        semantic colors (success/warning/error) from the theme if they differ
        from the algorithmically-derived defaults.
        """
        # Pick the best root color: accent > primary > fallback green
        phosphex = str(theme.accent or theme.primary or "#39ff14")
        cascade = cls(phosphex=phosphex, preset_name=theme.name or "custom")

        # Override semantic colors from Textual theme if provided
        if theme.success:
            cascade.color_success = str(theme.success)
        if theme.warning:
            cascade.color_warning = str(theme.warning)
        if theme.error:
            cascade.color_danger = str(theme.error)
        if theme.primary:
            cascade.color_info = str(theme.primary)

        return cascade

    @classmethod
    def from_preset(cls, preset_key: str) -> "ColorCascade":
        """Create a ColorCascade from a preset name.

        The "styrene" key returns the hand-tuned brand cascade;
        all other keys use the algorithmic forge world derivation.
        """
        if preset_key == "styrene":
            from styrened.tui.themes.styrene_brand import create_styrene_cascade

            return create_styrene_cascade()
        preset = get_preset(preset_key)
        if preset is None:
            raise ValueError(f"Unknown forge world preset: {preset_key}")
        return cls(phosphex=preset.phosphex, preset_name=preset.name)

    def generate_css_variables(self) -> str:
        """Generate CSS variable definitions for the palette.

        Note: Textual doesn't support CSS custom properties in the same
        way browsers do, so these are for documentation/reference.
        """
        return f"""/* Generated from phosphex: {self.phosphex} ({self.preset_name}) */

/* Phosphor Shades */
--color-bright: {self.bright};
--color-medium: {self.medium};
--color-dim: {self.dim};
--color-dark: {self.dark};

/* Backgrounds */
--bg-screen: {self.bg_screen};
--bg-panel: {self.bg_panel};
--bg-panel-elevated: {self.bg_panel_elevated};
--bg-hover: {self.bg_hover};

/* Borders */
--border-dim: {self.border_dim};
--border-medium: {self.border_medium};
--border-bright: {self.border_bright};
--corner-highlight: {self.corner_highlight};

/* Status */
--status-online: {self.status_online};
--status-offline: {self.status_offline};
--status-pending: {self.status_pending};
--status-scanning: {self.status_scanning};
--status-info: {self.status_info};

/* Semantic */
--color-success: {self.color_success};
--color-warning: {self.color_warning};
--color-danger: {self.color_danger};
--color-info: {self.color_info};
"""

    def to_dict(self) -> dict[str, str]:
        """Export palette as dictionary for programmatic use."""
        return {
            "phosphex": self.phosphex,
            "preset_name": self.preset_name,
            "bright": self.bright,
            "medium": self.medium,
            "dim": self.dim,
            "dark": self.dark,
            "bg_screen": self.bg_screen,
            "bg_panel": self.bg_panel,
            "bg_panel_elevated": self.bg_panel_elevated,
            "bg_hover": self.bg_hover,
            "border_dim": self.border_dim,
            "border_medium": self.border_medium,
            "border_bright": self.border_bright,
            "corner_highlight": self.corner_highlight,
            "status_online": self.status_online,
            "status_offline": self.status_offline,
            "status_pending": self.status_pending,
            "status_scanning": self.status_scanning,
            "status_info": self.status_info,
            "color_success": self.color_success,
            "color_warning": self.color_warning,
            "color_danger": self.color_danger,
            "color_info": self.color_info,
        }

    def to_textual_theme(self, name: str | None = None) -> "Theme":
        """Generate a Textual Theme from this cascade.

        Args:
            name: Theme name. Defaults to lowercase preset key.

        Returns:
            A Textual Theme configured with cascade colors.
        """
        from textual.theme import Theme

        theme_name = name or self.preset_name.lower().replace(" ", "-")

        return Theme(
            name=theme_name,
            # Core phosphor palette
            primary=self.medium,
            secondary=self.dark,
            accent=self.bright,
            # Text and backgrounds
            foreground=self.medium,
            background=self.bg_screen,
            surface=self.bg_panel,
            panel=self.dim,
            # Status colors (semantic, not phosphex-derived)
            success=self.color_success,
            warning=self.color_warning,
            error=self.color_danger,
            dark=True,
            variables={
                # Borders
                "border": self.border_medium,
                "border-blurred": self.border_dim,
                # Cursor
                "block-cursor-background": self.bright,
                "block-cursor-foreground": self.bg_screen,
                # Footer
                "footer-key-foreground": self.bright,
                "footer-background": self.bg_panel,
                # Input
                "input-selection-background": f"{self.bright} 25%",
                "input-cursor-background": self.bright,
                # Scrollbar
                "scrollbar": self.dark,
                "scrollbar-hover": self.dim,
                "scrollbar-active": self.medium,
            },
        )


def generate_all_themes() -> dict[str, "Theme"]:
    """Generate Textual themes for all presets including the styrene brand theme.

    Returns:
        Dictionary mapping preset keys to Theme objects.
    """
    from textual.theme import Theme

    from styrened.tui.themes.styrene_brand import STYRENE_THEME_KEY, create_styrene_theme

    themes: dict[str, Theme] = {
        STYRENE_THEME_KEY: create_styrene_theme(),
    }
    for key in FORGE_WORLD_ORDER:
        cascade = ColorCascade.from_preset(key)
        themes[key] = cascade.to_textual_theme(name=key)
    return themes


# =============================================================================
# DEFAULT CASCADES
# =============================================================================

# Default Imperial CRT palette (Mars Pattern)
IMPERIAL_CRT_CASCADE = ColorCascade.from_preset("mars")

# Backwards compatibility alias
MARS_CASCADE = IMPERIAL_CRT_CASCADE

# Quick access to popular alternatives
RYZA_CASCADE = ColorCascade.from_preset("ryza")
STYGIES_CASCADE = ColorCascade.from_preset("stygies")
LUCIUS_CASCADE = ColorCascade.from_preset("lucius")
METALICA_CASCADE = ColorCascade.from_preset("metalica")
