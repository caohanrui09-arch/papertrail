"""Versioned file paths only; original frozen scorer and metrics unchanged."""
from pathlib import Path
from scripts import score_state_constraints as base


def summarize(split: str) -> dict:
    base.ROOT=Path('data/stage21-isolated');base.REPORT=Path('reports/stage21-isolated')
    return base.summarize(split)


def main() -> None:
    base.ROOT=Path('data/stage21-isolated');base.REPORT=Path('reports/stage21-isolated')
    base.main()


if __name__=='__main__':main()
