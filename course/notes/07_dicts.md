# Dictionaries

## Keys and values
A dictionary maps keys to values: `ages = {"sara": 20, "omar": 22}`. You read a value with its
key, `ages["sara"]`, and add or change one with `ages["lina"] = 19`. Reading a key that is not
there raises `KeyError`.

```python
stock = {"apple": 3}
stock["apple"] = stock["apple"] + 2  # fine: "apple" exists
# stock["pear"] = stock["pear"] + 1   # KeyError: "pear" is not there yet
```

`d.get(key, default)` returns the default instead of raising an error when the key is missing.
`key in d` tells you whether the key exists.

## Counting with a dictionary
To count how often each thing appears, use the things as keys and their counts as values. For
each item, add one to its count, starting from 0 the first time you see it. Two common ways:

```python
tally = {}
for letter in "banana":
    if letter not in tally:
        tally[letter] = 0
    tally[letter] += 1
# tally is {"b": 1, "a": 3, "n": 2}
```

The other way uses `get` with 0 as the default, so a new key starts at 0 in one step. Before
counting, make sure equal things really look equal: clean words the same way first (case,
punctuation), or "Word" and "word" become two keys.

## What can be a key
Keys must be **hashable**: values that can't change, like numbers, strings and tuples. A list
can change, so it can't be a key: `d[[1, 2]] = 5` raises `TypeError: unhashable type: 'list'`.

When you want to use a list as a key, turn it into something fixed first: a tuple
(`tuple(items)`) or a string (`"".join(letters)`). For example, two words with the same
letters give the same sorted string, so the sorted string can be the key of their group.

Values have no such rule: a value can be a list, which is how you collect items into groups.

## Looping over a dictionary
A `for` loop over a dictionary goes through its **keys**. `d.values()` gives the values, and
`d.items()` gives (key, value) pairs, which you can unpack in the loop:

```python
prices = {"tea": 2, "cake": 5}
for item, price in prices.items():
    print(item, price)
```

Dictionaries remember the order in which keys were added. Don't add or remove keys while you
loop over the same dictionary; loop over a copy of the keys (`list(d)`) if you must.

## Is it there? `in` versus truthiness
`if d.get(key):` does **not** ask whether the key exists. It asks whether the stored value is
"truthy". The values 0, `""`, `[]` and `None` are all false, so a key whose value is 0 looks
missing. That is a real bug when the value is a position (index 0) or a count of 0.

To ask "is the key there?", write `if key in d:`. Use `get` when you want the value with a
fallback, and `in` when you want a yes/no answer about the key.
