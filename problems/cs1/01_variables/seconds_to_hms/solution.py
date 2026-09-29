def seconds_to_hms(seconds: int) -> list[int]:
    """Convert a number of seconds to [hours, minutes, seconds]."""
    hours = seconds // 3600
    minutes = seconds % 3600 // 60
    secs = seconds % 60
    return [hours, minutes, secs]
