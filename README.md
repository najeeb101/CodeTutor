# CodeTutor

A CS1 (intro to programming) Python practice platform with instant auto-grading, and an AI lab
built on top of it. Every problem has automatic visible and hidden tests. The same grader scores
student submissions, evaluates AI models (pass rates), and serves as the reward function for
reinforcement-learning training of a small code model.

**Status:** Week 1 in progress (problem bank + auto-grader).

## Requirements
- Linux or macOS (on Windows, use WSL2); the grader's sandbox uses POSIX features
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)

## Install and test
```bash
make install   # install dependencies and the package (editable)
make test      # run the test suite
make lint      # ruff lint + format check
make all       # lint + test + validate
```

## Project layout
- `problems/`: the problem bank (one folder per problem)
- `src/codetutor/`: problem schema/loader and the grader
- `scripts/`: validator, expected-output filler, grading CLI, dataset builder
- `tests/`: test suite
- `docs/`: design docs and notes
