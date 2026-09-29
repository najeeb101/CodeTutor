def seconds_to_hms(seconds: int) -> list[int]:
    hours = seconds // 3600
    minutes = seconds // 60  # bug: counts ALL the minutes, including the ones already in the hours
    secs = seconds % 60
    return [hours, minutes, secs]
