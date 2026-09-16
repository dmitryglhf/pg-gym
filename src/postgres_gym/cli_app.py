"""Unified Typer entrypoint for the platform and local Gym commands."""

from postgres_gym_platform.cli_app import app, main

__all__ = ["app", "main"]


if __name__ == "__main__":
    main()
