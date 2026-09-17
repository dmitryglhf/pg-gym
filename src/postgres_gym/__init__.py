from importlib.metadata import version

from postgres_gym.gym import EpisodeResult, Gym, TaskSpec

__version__ = version("postgres-gym")

__all__ = ["EpisodeResult", "Gym", "TaskSpec", "__version__"]
