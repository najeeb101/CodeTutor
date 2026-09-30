OPENER_FOR = {")": "(", "]": "[", "}": "{"}  # closing bracket -> its opening bracket


def valid_parentheses(s: str) -> bool:
    """Return True if the brackets ()[]{} in s are properly matched and nested."""
    stack = []  # opening brackets that are not closed yet; the last one is on top
    for char in s:
        if char in OPENER_FOR:  # a closing bracket
            if not stack or stack.pop() != OPENER_FOR[char]:
                return False
        else:
            stack.append(char)
    return not stack  # anything left was opened but never closed
