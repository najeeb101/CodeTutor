# Strings

## Strings cannot be changed
A string is immutable: once it exists, its characters can't be changed. `word[0] = "H"` raises
`TypeError: 'str' object does not support item assignment`. Instead, build a **new** string and
give it a name.

```python
word = "hello"
word = "H" + word[1:]  # a new string "Hello"
```

To build a string piece by piece, collect the pieces in a list and join them at the end:
`"".join(pieces)`. Adding to a string with `+=` in a loop also works for short texts.

## Indexing and slicing
`text[0]` is the first character and `text[-1]` the last. A slice `text[a:b]` gives the
characters from position `a` up to, but not including, `b`. Leaving out a side means "from the
start" or "to the end": `text[:3]` is the first three characters, `text[3:]` the rest.

A third number is the step: `text[::2]` takes every second character, and `text[::-1]` walks
backwards, which reverses the string. Slices never raise an `IndexError`: `"abc"[1:100]` is
simply `"bc"`. Reading a single position that does not exist, like `"abc"[5]`, does raise one.

## Splitting text into words
`text.split()` with **no argument** splits on any run of whitespace (spaces, tabs, new lines)
and drops empty pieces: `"a  b ".split()` is `["a", "b"]`.

`text.split(" ")` splits on every single space, so two spaces in a row give an empty string:
`"a  b".split(" ")` is `["a", "", "b"]`. That is a frequent cause of wrong word counts and
extra spaces.

The opposite of `split` is `join`: `" ".join(["a", "b"])` is `"a b"`. Joining with a separator
puts it only *between* the pieces, so there is no extra space at the end.

## Upper and lower case
String comparisons are case-sensitive: `"Hello" == "hello"` is false, and `"A"` and `"a"` are
different characters. When case should not matter, change both sides to the same case first:
`text.lower()` or `text.upper()`. These return a new string; the original stays as it was, so
keep the result: `text = text.lower()`.

To remove characters from the ends, use `strip`: `"  hi  ".strip()` is `"hi"`, and
`"hi!".strip("!?.")` removes punctuation from both ends only, never from the middle.

## Checking characters
You can test what kind of character you have:
- `ch.isalpha()`: a letter;
- `ch.isdigit()`: a digit 0–9;
- `ch.isalnum()`: a letter or a digit;
- `ch.isspace()`: whitespace.

The `in` operator checks membership in a string: `ch in "aeiou"` is true for a lowercase vowel.
Remember that `"A" in "aeiou"` is false, so lower the character first if capitals should count.
These methods also accept letters and digits from other alphabets (for example "é"). Our
problems use plain English text, and their descriptions say so.
