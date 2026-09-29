def is_leap_year(year: int) -> bool:
    return year % 4 == 0  # bug: ignores the 100 and 400 exceptions
