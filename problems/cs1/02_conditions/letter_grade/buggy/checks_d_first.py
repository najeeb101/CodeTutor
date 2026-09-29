def letter_grade(score: int) -> str:
    if score < 0 or score > 100:
        return "Invalid"
    if score >= 60:  # bug: checks the lowest pass grade first, so 95 stops here as a "D"
        return "D"
    if score >= 70:
        return "C"
    if score >= 80:
        return "B"
    if score >= 90:
        return "A"
    return "F"
