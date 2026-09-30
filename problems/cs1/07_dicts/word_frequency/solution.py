PUNCTUATION = ".,!?;:"


def word_frequency(text: str) -> dict[str, int]:
    """Return a dict that maps each lowercase word in text to how often it appears."""
    counts = {}
    for word in text.split():  # no argument: splits on spaces, tabs and new lines
        word = word.strip(PUNCTUATION).lower()
        if word:  # "..." becomes "", which is not a word
            counts[word] = counts.get(word, 0) + 1
    return counts
