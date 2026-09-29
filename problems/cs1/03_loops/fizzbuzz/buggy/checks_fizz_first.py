def fizzbuzz(n: int) -> list[str]:
    result = []
    for number in range(1, n + 1):
        if number % 3 == 0:  # bug: 15 stops here as "Fizz"; the FizzBuzz branch is never reached
            result.append("Fizz")
        elif number % 5 == 0:
            result.append("Buzz")
        elif number % 15 == 0:
            result.append("FizzBuzz")
        else:
            result.append(str(number))
    return result
