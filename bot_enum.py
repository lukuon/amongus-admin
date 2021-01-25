from enum import Enum


class ActionReaction(str, Enum):
    START = "▶️"
    STOP = "⏹"
    CLOSE = "❌"
    DEAD = "☠️"
    GATHER = "📢"
    MUTE = "🔇"


class AmongUsSessionStatus(int, Enum):
    ALIVE = 0
    DEAD = 1
