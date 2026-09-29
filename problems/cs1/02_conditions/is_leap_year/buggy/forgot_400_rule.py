def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and year % 100 != 0  # bug: forgets that 2000 (divisible by 400) is leap
