from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from prospectlens.config import SportConfig
from tests.conftest import CONFIG_DIR


def _raw() -> dict[str, Any]:
    with (CONFIG_DIR / "sports" / "football.yaml").open(encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def test_football_config_is_valid(cfg: SportConfig) -> None:
    assert {g.letter for g in cfg.goals} == {"A", "B", "C"}
    assert cfg.age.max_search_age == 25
    assert cfg.macro_of["FB"] == "DF"
    for m in cfg.metrics:
        assert m.description_it and m.how_to_read_it, m.code


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["metrics"][0].update(roles=["XX"]), "ruolo sconosciuto XX"),
        (lambda d: d["metrics"][0].update(requires="telepatia"), "tipo di dato sconosciuto"),
        (lambda d: d["metrics"][0].pop("stat"), "richiede 'stat'"),
        (lambda d: d["goals"][1]["requires"].append("xx"), "lente impact"),
        (lambda d: d["age"]["max_search_age_by_goal"].update(nope=30), "lente sconosciuta"),
        (lambda d: d["age_curves"].pop("GK"), "age_curves"),
        (lambda d: d["sport"].update(typo=1), "Extra inputs"),
    ],
)
def test_invalid_config_is_rejected(mutate: Any, message: str) -> None:
    data = _raw()
    mutate(data)
    with pytest.raises(ValidationError, match=message):
        SportConfig.model_validate(data)


def test_import_plan_parsing() -> None:
    from prospectlens.cli import parse_plan

    assert parse_plan("138,942,943:2024; 136:2024\n") == [([138, 942, 943], 2024), ([136], 2024)]
    assert parse_plan("") == []
    assert parse_plan('"136:2024"') == [([136], 2024)]  # virgolette da .env via make
