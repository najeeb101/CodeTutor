def is_leap_year(year: int) -> bool:
    """Return True if `year` is a leap year in the Gregorian calendar."""
    if year % 400 == 0:
        return True
    if year % 100 == 0:
        return False
    return year % 4 == 0
