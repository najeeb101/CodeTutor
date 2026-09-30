OPENER_FOR = {")": "(", "]": "[", "}": "{"}


def valid_parentheses(s: str) -> bool:
    stack = []
    for char in s:
        if char in OPENER_FOR:
            if stack.pop() != OPENER_FOR[char]:  # bug: IndexError when the stack is empty
                return False
        else:
            stack.append(char)
    return not stack
