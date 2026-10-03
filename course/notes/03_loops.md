# Loops

## for loops and range
A `for` loop runs its block once for each item. `range` makes a sequence of whole numbers:
`range(5)` is 0, 1, 2, 3, 4, and `range(2, 6)` is 2, 3, 4, 5. **The stop value is never
included.** To go from 1 up to and including n, write `range(1, n + 1)`.

```python
for step in range(1, 4):
    print(step)  # 1, then 2, then 3
```

`range(start, stop, step)` takes a third number for the step size: `range(0, 10, 3)` is 0, 3,
6, 9, and `range(5, 0, -1)` counts down 5, 4, 3, 2, 1. If your loop does one step too few or
too many, look at the stop value first. This is called an off-by-one error, and it is the most
common loop bug.

## while loops must make progress
A `while` loop repeats as long as its condition is true. Something inside the loop must change
so that the condition becomes false one day; otherwise the loop never ends, and the grader
stops your code with a timeout.

```python
countdown = 3
while countdown > 0:
    print(countdown)
    countdown -= 1  # without this line the loop runs forever
```

When a loop never stops, ask: which variable does the condition look at, and does every pass
through the loop move it closer to the end? Watch out for values that jump over the end point,
or that never reach it (for example a negative number when you count down to exactly 0).

## The accumulator pattern
To build up a result in a loop, start with an empty or neutral value before the loop and
update it on every step. For a sum, start at 0; for a product, start at 1 (starting at 0 makes
every product 0); for a list, start with `[]`.

```python
scores = [4, 7, 1]
best = scores[0]
for score in scores:
    if score > best:
        best = score
```

Put the start value **before** the loop. If you set it inside the loop, it is reset on every
pass. Return the result **after** the loop, not inside it, unless you really want to stop early.

## Checking divisibility
`a % b` is the remainder of `a` divided by `b`. A number is divisible by `b` exactly when the
remainder is 0: `12 % 3 == 0` is true and `13 % 3 == 0` is false. Even numbers are those with
`x % 2 == 0`.

To test "divisible by both 3 and 5", you can check `x % 3 == 0 and x % 5 == 0`. Since 3 and 5
share no factor, that is the same as `x % 15 == 0`. When several rules can be true for the same
number, check the combined rule before the single ones (see the conditions note).

## Edge cases: zero, one and negative numbers
Loops often work for "normal" inputs and fail at the edges. Before you submit, try:
- **0**: does a loop over `range(0)` run zero times, and is the answer right then? A number like
  0 still has one digit.
- **1**: the smallest normal case.
- **negative numbers**: `-5 // 10` is `-1`, not 0, so a loop that divides by 10 until it reaches
  0 never stops for a negative start. Work with `abs(n)` when only the size of the number
  matters.

Reading the task's examples and constraints tells you which edges can appear.
