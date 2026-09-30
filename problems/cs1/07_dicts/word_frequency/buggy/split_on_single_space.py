def word_frequency(text: str) -> dict[str, int]:
    counts = {}
    for word in text.split(" "):  # bug: split(" ") does not split on new lines or tabs
        word = word.strip(".,!?;:").lower()
        if word:
            counts[word] = counts.get(word, 0) + 1
    return counts
