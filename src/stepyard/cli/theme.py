"""
Stepyard CLI Design Tokens.

Single source of truth for the visual identity of the CLI:
color palette, ASCII logo, version string, and shared interactive styles.
"""

import questionary

# ─────────────────────────────────────────────────────────────────────────────
#  Version
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "2.0.0"

# ─────────────────────────────────────────────────────────────────────────────
#  Color palette (Modern terminal UI)
# ─────────────────────────────────────────────────────────────────────────────

C_PRIMARY = "#38bdf8"
C_ACCENT = "#a78bfa"
C_SUCCESS = "#34d399"
C_ERROR = "#fb7185"
C_WARN = "#fbbf24"
C_MUTED = "#64748b"
C_WHITE = "#f8fafc"
C_BOLD = "bold bright_white"
C_HINT = "#94a3b8"
C_DIM = "#1e293b"

# ─────────────────────────────────────────────────────────────────────────────
#  ASCII Logo
# ─────────────────────────────────────────────────────────────────────────────

LOGO = r"""
  ███████╗████████╗███████╗██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗
  ██╔════╝╚══██╔══╝██╔════╝██╔══██╗╚██╗ ██╔╝██╔══██╗██╔══██╗██╔══██╗
  ███████╗   ██║   █████╗  ██████╔╝ ╚████╔╝ ███████║██████╔╝██║  ██║
  ╚════██║   ██║   ██╔══╝  ██╔═══╝   ╚██╔╝  ██╔══██║██╔══██╗██║  ██║
  ███████║   ██║   ███████╗██║        ██║   ██║  ██║██║  ██║██████╔╝
  ╚══════╝   ╚═╝   ╚══════╝╚═╝        ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ """

# ─────────────────────────────────────────────────────────────────────────────
#  Shared questionary style
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_STYLE = questionary.Style(
    [
        ("qmark", "fg:#38bdf8 bold"),
        ("question", "fg:#f8fafc bold"),
        ("answer", "fg:#34d399 bold"),
        ("pointer", "fg:#a78bfa bold"),
        ("highlighted", "fg:#f8fafc bold bg:#1e293b"),
        ("selected", "fg:#f8fafc bold bg:#1e293b"),
        ("separator", "fg:#334155"),
        ("instruction", "fg:#94a3b8 italic"),
        # Custom classes for the interactive table
        ("col_success", "fg:#34d399"),
        ("col_error", "fg:#fb7185"),
        ("col_primary", "fg:#38bdf8"),
        ("col_accent", "fg:#a78bfa bold"),
        ("col_muted", "fg:#64748b"),
        ("col_warn", "fg:#fbbf24"),
        ("col_white", "fg:#f8fafc"),
        ("col_dim", "fg:#1e293b"),
        ("sep", "fg:#334155"),
    ]
)
