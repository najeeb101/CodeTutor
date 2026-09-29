def seconds_to_hms(seconds: int) -> list[int]:
    hours = seconds // 3600 % 24  # bug: clock thinking; a duration of 24 hours is not 0 hours
    minutes = seconds % 3600 // 60
    secs = seconds % 60
    return [hours, minutes, secs]
