# automatic_timetable_py

The concept is the same as in the [`automatic_timetable`](https://github.com/oleh-devlab/automatic_timetable) repository, but it is written in Python and uses Google OR-Tools.

The previous version of `automatic_timetable` written in C++ has no external dependencies. Writing my own algorithms that take a large number of conditions into account and optimally solve an NP-hard problem takes quite a while, so I decided to try a ready-made solution.

## Usage

To run the main application, use the following command from the root directory of the project:

```bash
python src/main.py
```

## Testing

To run all unit tests, navigate to the `src` directory and use the `unittest discover` command:

```bash
cd src
python -m unittest discover
```

Alternatively, you can run the tests directly from the root directory:

```bash
python -m unittest discover src
```
