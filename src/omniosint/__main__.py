"""Allows `python -m omniosint ...`, which works without the console script on PATH."""

from omniosint.cli.main import main

if __name__ == "__main__":
    main()
