def word_frequency(text: str) -> dict[str, int]:
    counts = {}
    for word in text.split():
        word = word.strip(".,!?;:")  # bug: no .lower(), so "The" and "the" are counted apart
        if word:
            counts[word] = counts.get(word, 0) + 1
    return counts
