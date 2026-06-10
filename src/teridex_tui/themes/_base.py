from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Theme:
    """A Teridex theme rendered as Textual design tokens."""

    name: str
    background: str
    foreground: str
    surface: str
    primary: str
    accent: str
    success: str
    warning: str
    error: str

    def as_variables(self) -> dict[str, str]:
        return {
            "background": self.background,
            "foreground": self.foreground,
            "surface": self.surface,
            "primary": self.primary,
            "accent": self.accent,
            "success": self.success,
            "warning": self.warning,
            "error": self.error,
        }
