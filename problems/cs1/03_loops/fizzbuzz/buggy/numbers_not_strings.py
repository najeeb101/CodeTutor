def fizzbuzz(n: int) -> list[str]:
    result = []
    for number in range(1, n + 1):
        if number % 15 == 0:
            result.append("FizzBuzz")
        elif number % 3 == 0:
            result.append("Fizz")
        elif number % 5 == 0:
            result.append("Buzz")
        else:
            result.append(number)  # bug: the int 1 is not the string "1"
    return result
