"""Seed the dev/demo dataset (Data Model §7).

Placeholder for Phase 0: the content schema (spaces/books/pages) lands in Epic B,
at which point this script creates the multi-space, multi-version, multi-locale
demo used by the test host and E2E tests. For now it is a safe no-op so the
documented `make seed` / compose command does not fail.
"""

from __future__ import annotations


def main() -> None:
    print("[seed] No content schema yet (Phase 0). Seeding is implemented in Epic B.")


if __name__ == "__main__":
    main()
