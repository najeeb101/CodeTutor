def reverse_words(sentence: str) -> str:
    """Return the words of sentence in reverse order, separated by single spaces."""
    words = sentence.split()
    words.reverse()
    return " ".join(words)
