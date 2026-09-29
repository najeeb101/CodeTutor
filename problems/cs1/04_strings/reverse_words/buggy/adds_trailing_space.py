def reverse_words(sentence: str) -> str:
    result = ""
    for word in reversed(sentence.split()):
        result += word + " "  # bug: also adds a space after the last word
    return result
