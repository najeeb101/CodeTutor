def seconds_to_hms(seconds: int) -> list[int]:
    hours = seconds / 3600  # bug: / gives a float with decimals (1.0169...), not whole hours
    minutes = seconds % 3600 // 60
    secs = seconds % 60
    return [hours, minutes, secs]
