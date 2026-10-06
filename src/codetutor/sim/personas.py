"""Who is in the simulated class, and every number that shapes it (Week 5 Step 1).

All the knobs are in `CohortConfig`, so a different class is one changed value, and the
config is written next to the generated file (its meta), so every run says how it was made.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Persona(StrEnum):
    """How a simulated student behaves. Only the cohort file's labels know it, never the DB."""

    STRONG = "strong"
    AVERAGE = "average"
    STRUGGLING = "struggling"
    QUITTER = "quitter"  # honest, but stops coming after a few modules
    COPIER = "copier"  # often pastes another student's accepted code, disguised
    AI_USER = "ai_user"  # often pastes a model's answer


class PersonaSpec(BaseModel):
    """One persona: how many students, their skill, their persistence, how often they cheat."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=0)
    skill_mean: float  # θ on the Rasch scale: 0 = average, +1.5 = strong, -1.5 = struggling
    max_attempts: int = Field(ge=1)  # honest attempts on one problem before giving up
    cheat_share: float = Field(default=0.0, ge=0, le=1)  # share of problems they cheat on


class CohortConfig(BaseModel):
    """Every number of one simulated class. Same config + same pools → the same file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = 0
    course_start: datetime = datetime(2026, 9, 7, tzinfo=UTC)  # a Monday; module m = week m
    personas: dict[Persona, PersonaSpec] = {
        Persona.STRONG: PersonaSpec(count=14, skill_mean=1.5, max_attempts=3),
        Persona.AVERAGE: PersonaSpec(count=20, skill_mean=0.0, max_attempts=4),
        Persona.STRUGGLING: PersonaSpec(count=12, skill_mean=-1.5, max_attempts=5),
        Persona.QUITTER: PersonaSpec(count=6, skill_mean=0.0, max_attempts=4),
        Persona.COPIER: PersonaSpec(count=4, skill_mean=-0.5, max_attempts=3, cheat_share=0.6),
        Persona.AI_USER: PersonaSpec(count=4, skill_mean=0.0, max_attempts=3, cheat_share=0.6),
    }
    skill_sd: float = 0.5  # spread of θ inside a persona
    # True difficulty b: easy / medium / hard, plus a seeded jitter per problem.
    difficulty_base: dict[str, float] = {"easy": -1.0, "medium": 0.0, "hard": 1.0}
    difficulty_jitter_sd: float = 0.3
    learning_per_attempt: float = 0.4  # attempt k succeeds with sigmoid(θ - b + 0.4·(k-1))
    quitter_last_module: tuple[int, int] = (3, 5)  # a quitter's last module, inclusive range
    own_style_share: float = 0.7  # honest code that gets the student's own variable names
    honest_paste_share: float = 0.15  # honest submits with a small paste of their own code
    # Step 2a: the cases that make paste detection a real trade-off.
    # Honest students who write in their own editor and paste whole programs (a trait):
    ide_paster_share: float = 0.1  # of the honest personas' students
    ide_paste_problem_share: float = 0.8  # of an IDE paster's problems
    retype_share: float = 0.3  # of cheating submissions typed in by hand instead of pasted
    # Week 2's 7B answers: seeds 0-4 are Step 2's "known AI answers" (never submitted here),
    # seeds 5-9 are what simulated AI users paste. Keeps the AI detector from seeing its own
    # reference text in the test data.
    reference_seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    ai_user_seeds: tuple[int, ...] = (5, 6, 7, 8, 9)
    ai_max_pastes: int = Field(default=2, ge=1)  # an AI user pastes at most this many answers

    @property
    def students(self) -> int:
        """How many students the class has."""
        return sum(spec.count for spec in self.personas.values())


HONEST_PERSONAS = frozenset({Persona.STRONG, Persona.AVERAGE, Persona.STRUGGLING, Persona.QUITTER})
