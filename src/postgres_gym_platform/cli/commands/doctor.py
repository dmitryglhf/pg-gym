from ... import __version__


def doctor() -> None:
    import shutil
    import sys

    from ...config import project_root
    from ..output import show

    show(
        {
            "version": __version__,
            "python": sys.version.split()[0],
            "root": str(project_root()),
            "docker": shutil.which("docker"),
            "nvidia_smi": shutil.which("nvidia-smi"),
            "suites_present": (project_root() / "suites").is_dir(),
        }
    )
