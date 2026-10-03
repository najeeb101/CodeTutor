# Recursion and problem solving

## Base case and recursive case
A recursive function calls itself on a smaller version of the problem. It needs two parts:
- a **base case**: the smallest input, answered directly without another call;
- a **recursive case**: break the input into a smaller piece, call the function on it, and use
  that answer.

```python
def countdown(n):
    if n == 0:  # base case
        return ["go"]
    return [n] + countdown(n - 1)  # recursive case: a smaller n
```

Every recursive call must get closer to the base case. Choose the base case carefully: for a
list, the empty list is usually the right one, not a list with one item.

## RecursionError: maximum recursion depth exceeded
Each call waits for the call it made, and Python allows only about 1000 calls waiting at the
same time. Going deeper raises `RecursionError`. There are two usual causes:
- **No base case, or one that is never reached.** For example, the base case checks `n == 0`
  but the calls go 5, 3, 1, -1, … and skip 0.
- **The input is simply too deep.** Even correct recursion fails on a list of 5000 items. Then
  a loop is the better tool.

Read the error's traceback: if the same line repeats hundreds of times, the function never
stopped calling itself.

## Repeated work: why naive recursion can be slow
Some recursive functions solve the same smaller problem again and again. The textbook example is
Fibonacci written as "fib(n) = fib(n - 1) + fib(n - 2)": fib(n - 1) also computes fib(n - 2),
and so on, so the number of calls roughly doubles with every step of n. fib(25) is quick, but
fib(40) takes hundreds of millions of calls.

Two fixes: remember the answers you already computed (memoization, for example with a
dictionary), or compute from the bottom up with a loop that keeps only the last two values.
The loop is simple and needs no recursion at all.

## The mutable default argument trap
Default values are created once, when the function is defined. A list as a default is
therefore **shared** between calls:

```python
def collect(item, bag=[]):  # one list, shared by every call
    bag.append(item)
    return bag


collect(1)  # [1]
collect(2)  # [1, 2]  -- the 1 is still there
```

This is especially sneaky in recursion, where a helper list is passed along. Use `None` as the
default and create a new list inside: `if bag is None: bag = []`.

## Halving the search: binary search
In a **sorted** list you don't need to look at every item. Look at the item in the middle: if
it is the target, you are done; if the target is bigger, it can only be in the right half;
if smaller, only in the left half. Throw away the other half and repeat.

Each step halves the part that is left, so a list of a million items needs only about 20 steps.
Keep two positions, the first and the last index the target can still be at, and stop when
they cross: then the target is not in the list. Off-by-one mistakes are common here, so trace a
list of two or three items by hand, with a target that is missing.

## Stacks: last in, first out
A stack is a pile: you add on top and take from the top. A Python list works as a stack with
`append` (push) and `pop` (take the last item). Stacks fit problems where the most recent open
thing must be closed first, like matching brackets: each closing bracket must match the latest
opening bracket that is still open. Counting brackets is not enough, because the order matters:
"([)]" has balanced counts but the wrong order. Before you pop, check that the stack isn't
empty.
