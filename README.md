<div align="center">

<img src="https://raw.githubusercontent.com/dmitryglhf/pg-gym/main/assets/slonik.svg" alt="logo" width="180"/>

# `PostgresGym`

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab.svg)](https://python.org)

An Interactive Environment for LLM Agents in Database-Engine Development

</div>

<div align="center">

<img src="https://raw.githubusercontent.com/dmitryglhf/pg-gym/main/assets/inference.png" alt="The inference view" width="720"/>

</div>

## Quickstart

Install with Python 3.12, uv, Docker Engine and Docker Compose v2 present:

```sh
uv tool install .
pg-gym platform start --source .
pg-gym platform registration-code
```

Open `http://localhost:9432`, create an account with the code and add a model connection in Settings. The same platform from a terminal:

```sh
pg-gym context add local --url http://localhost:9432
pg-gym auth login --username alice
pg-gym benchmark submit sql-function-set --task area --harness opencode --connection CONNECTION_ID --wait
```

Without a platform, the library runs a task on its own:

```python
from postgres_gym import Gym

gym = Gym("sql-function-set")
result = gym.run("area", "cli:opencode")
print(result.reward)
```

## Docs

The [documentation](docs/index.md) covers the instance, the task image, benchmarks, models, training, trajectory collection, the CLI, the library and the REST API. To serve it locally:

```sh
just doc
```
