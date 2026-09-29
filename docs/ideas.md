# Ideas for later weeks

Ideas that come up during a week but belong to a later week. Add them here instead of building them.


- **(Week 5, integrity) AST check for banned calls.** `merge_sorted` asks students not to use
  `sort()`/`sorted()`, but a timing test can't catch it (`sorted(a + b)` runs in C and is faster
  than a correct Python merge; measured 0.2 ms vs 1.8 ms at n = 10 000). An AST scan of the
  submission could flag banned calls. It should be a *flag for a human*, never an automatic 0.
