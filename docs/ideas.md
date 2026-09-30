# Ideas for later weeks

Ideas that come up during a week but belong to a later week. Add them here instead of building them.


- **(Week 5, integrity) AST check for banned calls.** `merge_sorted` asks students not to use
  `sort()`/`sorted()`, but a timing test can't catch it (`sorted(a + b)` runs in C and is faster
  than a correct Python merge; measured 0.2 ms vs 1.8 ms at n = 10 000). An AST scan of the
  submission could flag banned calls. It should be a *flag for a human*, never an automatic 0.

- **(Week 6, RL reward) Efficiency tests are worth very little under partial credit.** The naive
  `is_prime` (tries every number up to n) passes 13 of 14 tests and gets reward 0.93; only the one
  big prime times out. So an RL model gets almost no push to learn the fast algorithm. Options to
  test in Week 6: give efficiency tests more weight, or a bonus only when *all* tests pass.
  Measure first; don't change the reward blindly.
