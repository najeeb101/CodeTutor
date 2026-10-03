# Functions

## return vs print
`print` shows a value on the screen; `return` hands a value back to the code that called the
function. The grader calls your function and looks at what it **returns**. A function that only
prints returns `None`, so the test fails even if the right answer appears in the output.

```python
def double(x):
    print(x * 2)  # shows the value, but the function still returns None


def double_ok(x):
    return x * 2  # the caller gets the value
```

`return` also ends the function at once: code after it in the same block never runs. A `return`
inside a loop stops the whole loop on the first pass, which is only right when you want to stop
early.

## Parameters, arguments and default values
Parameters are the names in the `def` line; arguments are the values you pass in a call.
A parameter can have a default value, used when the caller leaves it out:

```python
def greet(name, greeting="Hello"):
    return f"{greeting}, {name}!"


greet("Sara")  # "Hello, Sara!"
greet("Sara", "Hi")  # "Hi, Sara!"
```

Defaults are made **once**, when the function is defined, not on every call. That is harmless
for numbers and strings, but a list or dict as a default is shared by every call. See the
recursion note for this trap.

## Scope: names inside a function
Names you create inside a function are local: they exist only while the function runs and
can't be seen outside. A function can read a name from outside, but assigning to it inside the
function makes a new local name instead of changing the outside one.

So a function should get what it needs through its parameters and give its answer through
`return`, not by changing names outside it. That makes it easy to test: the same arguments
always give the same result. Changing a list the caller passed in is a side effect too (see the
lists note).

## Fast enough: avoid needless work
The grader has a time limit, so code that is correct but very slow still fails with a timeout.
Look for loops that do far more steps than needed:
- **Stop early** when the answer is known, for example on the first match.
- **Use the right bound.** If a number has a divisor bigger than its square root, it also has
  one smaller, so a divisor search can stop at `d * d > n` instead of going all the way to n.
  For n around one billion, that is about 30,000 steps instead of a billion.
- **Avoid a loop inside a loop** when a set or dict lookup can replace the inner loop.

A quick check: count roughly how many steps your loops take for the largest input the task
allows.

## Guarding against bad or special input
Some inputs need care before the main calculation. Dividing by zero raises `ZeroDivisionError`,
and `%` by zero does too. If 0 is a valid input, handle it first, with its own `if` and the
answer the task asks for.

Read the task's rules for special values: numbers below 2 are not prime, 0 and 1 are special in
many maths problems, an empty text may have its own expected answer. A small check at the top
of the function (a "guard clause") keeps the rest of the code simple.
