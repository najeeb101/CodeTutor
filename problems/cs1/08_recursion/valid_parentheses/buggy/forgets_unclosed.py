OPENER_FOR = {")": "(", "]": "[", "}": "{"}


def valid_parentheses(s: str) -> bool:
    stack = []
    for char in s:
        if char in OPENER_FOR:
            if not stack or stack.pop() != OPENER_FOR[char]:
                return False
        else:
            stack.append(char)
    return True  # bug: brackets still on the stack were never closed, so "((" is not valid
