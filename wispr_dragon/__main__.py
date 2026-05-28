"""Allow `python -m wispr_dragon` to run the same entry point as the console script."""

from wispr_dragon.main import main

if __name__ == "__main__":
    raise SystemExit(main())
