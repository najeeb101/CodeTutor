# Lists

## Indexes and IndexError
The items of a list are numbered from 0, so a list of length 4 has the indexes 0, 1, 2 and 3.
`items[len(items)]` is one past the end and raises `IndexError: list index out of range`.
Negative indexes count from the end: `items[-1]` is the last item.

```python
letters = ["a", "b", "c"]
print(letters[2])  # "c"
print(letters[-1])  # also "c"
```

When you get an `IndexError`, print the index and the length just before the failing line.
Common causes: a loop that runs to `len(items)` inclusive, reading `items[i + 1]` on the last
step, or reading `items[0]` from an empty list.

## Changing a list vs making a new one
A list is mutable, and a name only points to it. After `b = a`, both names point to the **same**
list, so `b.append(1)` changes `a` too. A function that receives a list gets the caller's list,
not a copy: if it sorts, removes or appends, the caller sees the change.

When a task says "return a new list", don't touch the input. Build a result list, or make a
copy first with `list(items)` or `items[:]`.

```python
def with_extra(items):
    result = list(items)  # a copy: the caller's list stays the same
    result.append(0)
    return result
```

Some of our problems check that your function did not change its input.

## sort() vs sorted()
`items.sort()` sorts the list **in place**: it changes the list and returns `None`. So
`x = items.sort()` sets `x` to `None`, a classic bug. `sorted(items)` leaves the original alone
and returns a new sorted list.

Both accept `reverse=True` for largest first, and `key=` to sort by something else, for
example `sorted(words, key=len)` sorts words by length. Lists of lists or tuples are sorted by
their first item, then by the second when the first items are equal.

## Empty lists and other edge cases
Code that works for `[3, 1, 2]` can crash on `[]`: `items[0]`, `max(items)` and dividing by
`len(items)` all fail on an empty list. Check the task: if an empty list is allowed, decide
what the answer should be and handle it first, before the main work:

```python
def first_or_none(items):
    if not items:
        return None
    return items[0]
```

Also try a list with one item, a list where all items are the same, and a list with negative
numbers. A start value of 0 for "the largest so far" is wrong when every number is negative.

## Membership and keeping the order
`x in items` checks whether a value is in a list. It looks at the items one by one, so it is
slow for long lists. A `set` answers the same question much faster, but a set has no order:
turning a list into a set and back can shuffle the items.

To keep the first occurrence of each value **in the original order**, walk through the list and
keep two things: a set of values you have already seen (fast to check), and a result list that
you append to the first time you see a value.
