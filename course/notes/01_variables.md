# Variables and arithmetic

## Names and values
A variable is a name for a value. `price = 12` makes the name `price` point to the value 12.
Python has a few basic types: `int` for whole numbers (12, -3), `float` for numbers with a
decimal point (2.5, 12.0), `str` for text ("hello") and `bool` for `True` and `False`. You can
ask for the type of a value with `type()`.

```python
price = 12
rate = 0.5
print(type(price), type(rate))  # <class 'int'> <class 'float'>
```

`12` and `12.0` are equal when you compare them with `==`, but they are different types. When
a task asks for a float, return a float: a function that should give `12.0` and returns `12`
can fail a strict test.

## Division and remainder
Python has three operators for dividing:
- `/` is true division. It always gives a float: `7 / 2` is `3.5`, and `6 / 2` is `3.0`.
- `//` is floor division. It rounds down to a whole number: `7 // 2` is `3`. Careful with
  negative numbers: `-7 // 2` is `-4`, because it rounds *down*, not toward zero.
- `%` is the remainder: `7 % 2` is `1`. It answers "what is left over?"

```python
total_minutes = 135
hours = total_minutes // 60  # 2 full hours
minutes = total_minutes % 60  # 15 minutes left over
```

If an average or a percentage comes out as a whole number when you expected decimals, check
whether you used `//` where you meant `/`.

## Operator precedence
Python does `*`, `/`, `//` and `%` before `+` and `-`, just like in maths. So `2 + 3 * 4` is
`14`, not `20`. `**` (power) comes even earlier. When you want another order, use parentheses:
`(2 + 3) * 4` is `20`. A common mistake is a formula like `a + b + c / 3`: only `c` is divided
by 3. Write `(a + b + c) / 3` to divide the whole sum. When in doubt, add parentheses; they
make the order clear to the reader too.

## Floats are approximate
A float is stored in binary, and most decimal fractions can't be stored exactly. That is why
`0.1 + 0.2` prints `0.30000000000000004`. It is not a bug in Python; every language that uses
binary floats does this.

`round(x, 2)` rounds to two decimals, but the stored value may be a tiny bit below or above
what you typed. `2.675` is really stored as `2.67499999...`, so `round(2.675, 2)` gives `2.67`.
Also, when a value is exactly halfway, `round()` goes to the even neighbour: `round(2.5)` is `2`
and `round(3.5)` is `4`.

Never compare floats with `==` after a calculation. Compare with a small tolerance instead,
for example `abs(a - b) < 1e-9`.

## Converting between types
`int("42")` turns text into a whole number, `float("2.5")` into a float, and `str(42)` turns a
number into text. `int(3.9)` cuts off the decimals and gives `3`; it does not round. If you
need rounding, use `round()`. Text and numbers don't mix: `"Age: " + 5` is a `TypeError`. Use
`"Age: " + str(5)` or an f-string: `f"Age: {age}"`.
