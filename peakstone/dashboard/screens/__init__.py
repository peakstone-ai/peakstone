"""Dashboard modal screens — one module per screen family, split out of app.py (review R21)."""
from .challenges import ChallengesScreen
from .models import AddModelScreen, ModelsScreen, QuantScreen
from .pickers import BudgetScreen, ConfirmScreen, CtxScreen, ReasoningScreen
from .preflight import PreflightScreen, run_with_preflight
from .queue import QueueScreen
from .reproduce import ReproduceScreen
from .solution import SolutionScreen, _solution_body
from .update import UpdateScreen
from .wishlist import AddWishlistScreen, WishlistScreen

__all__ = [
    "AddModelScreen", "AddWishlistScreen", "BudgetScreen", "ChallengesScreen", "ConfirmScreen",
    "CtxScreen", "ModelsScreen", "PreflightScreen", "QuantScreen", "QueueScreen",
    "ReasoningScreen", "ReproduceScreen", "SolutionScreen", "UpdateScreen", "WishlistScreen",
    "_solution_body", "run_with_preflight",
]
