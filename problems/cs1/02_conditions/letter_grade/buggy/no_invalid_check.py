def letter_grade(score: int) -> str:
    # bug: never returns "Invalid"; 101 becomes "A" and -5 becomes "F"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
