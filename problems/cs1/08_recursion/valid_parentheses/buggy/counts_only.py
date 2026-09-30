def valid_parentheses(s: str) -> bool:
    # bug: equal counts are not enough, the order matters too. "([)]" has one of each
    # opener and closer, but the brackets cross, so it is not valid.
    return (
        s.count("(") == s.count(")")
        and s.count("[") == s.count("]")
        and s.count("{") == s.count("}")
    )
