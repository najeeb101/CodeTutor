def word_frequency(text: str) -> dict[str, int]:
    counts = {}
    for word in text.split():
        word = word.strip(".,!?;:").lower()
        # bug: no "if word:" check, so a lone "..." is counted as the empty word ""
        counts[word] = counts.get(word, 0) + 1
    return counts
