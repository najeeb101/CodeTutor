# Conditions

## if, elif and else
An `if` statement runs a block only when its condition is true. `elif` ("else if") is checked
only when every condition above it was false, and `else` runs when nothing matched. In one
`if`/`elif`/`else` chain, **at most one branch runs**: the first one whose condition is true.

```python
temperature = 30
if temperature > 35:
    print("very hot")
elif temperature > 25:
    print("warm")
else:
    print("mild")
```

Two separate `if` statements are different: both are checked, so both blocks can run. Use
`elif` when the cases exclude each other (only one answer is possible), and separate `if`s
when several things can be true at the same time.

## Order matters: most specific case first
Because only the first true branch of a chain runs, the order of the conditions can change the
answer. If an earlier condition is *wider* than a later one, the later one can never run. For
example, with `if size > 10:` before `elif size > 100:`, a size of 500 stops at the first
branch, and the second is dead code.

So put the narrowest condition first: the one that is true for the fewest values. When a
function gives a wrong category (a low grade for a high score, a general answer where a special
one was expected), walk through the chain by hand with that input and see which branch catches
it first.

## Comparisons and boundaries
`<` and `>` leave out the boundary; `<=` and `>=` include it. Many bugs sit exactly on a
boundary: a score of exactly 90, two equal numbers, a list with exactly one item. Read the task
carefully: "at least 90" means `>= 90`, "more than 90" means `> 90`.

Test the boundary values by hand: the value itself, one below and one above. Also think about
ties: if two values are equal, which one should win, and does your comparison allow it?

Python can chain comparisons: `0 <= x < 10` means "x is at least 0 and below 10".

## Combining conditions: and, or, not
`and` is true only when both sides are true. `or` is true when at least one side is true. `not`
flips true and false.

```python
age = 20
has_ticket = True
if age >= 18 and has_ticket:
    print("you may enter")
```

`and` is checked before `or`, so `a or b and c` means `a or (b and c)`. Use parentheses when
you mix them. A common mistake: `if x == 1 or 2:` is always true, because `2` on its own counts
as true. Write `if x == 1 or x == 2:` or `if x in (1, 2):`.

## Every path needs a return
A function that ends without reaching a `return` gives back `None`. With conditions, it is easy
to return a value in some branches and forget others.

```python
def sign(number):
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    # forgot zero: sign(0) returns None
```

If a test says your function returned `None`, follow the input through your code and find the
path that ends without a `return`. Often the fix is an `else` branch, or a `return` after the
last `if`.
