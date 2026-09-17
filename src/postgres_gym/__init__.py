from importlib.metadata import PackageNotFoundError, version

from postgres_gym.gym import EpisodeResult, Gym, TaskSpec

try:
    __version__ = version("postgres-gym")
except PackageNotFoundError:
    # The task image runs the sources from PYTHONPATH without installing them.
    __version__ = "0.0.0+source"

__all__ = ["EpisodeResult", "Gym", "TaskSpec", "__version__"]
