def fizzbuzz(n: int) -> list[str]:
    result = []
    for number in range(1, n):  # bug: range stops before n, so the last number is missing
        if number % 15 == 0:
            result.append("FizzBuzz")
        elif number % 3 == 0:
            result.append("Fizz")
        elif number % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(number))
    return result
