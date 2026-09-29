def reverse_words(sentence: str) -> str:
    words = sentence.split(" ")  # bug: with extra spaces, split(" ") gives empty strings ""
    words.reverse()
    return " ".join(words)
