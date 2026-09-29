def letter_grade(score: int) -> str:
    """Return the letter grade (A-F) for a score from 0 to 100, or "Invalid"."""
    if score < 0 or score > 100:
        return "Invalid"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
