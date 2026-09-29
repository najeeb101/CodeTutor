def letter_grade(score: int) -> str:
    if score < 0 or score > 100:
        return "Invalid"
    if score > 90:  # bug: > instead of >=, so exactly 90 gets a B (same for 80, 70, 60)
        return "A"
    if score > 80:
        return "B"
    if score > 70:
        return "C"
    if score > 60:
        return "D"
    return "F"
