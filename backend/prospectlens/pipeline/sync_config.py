"""Copia metriche e lenti dal YAML al database (il YAML resta la fonte di verità)."""

from sqlalchemy import delete
from sqlalchemy.orm import Session

from prospectlens.config import SportConfig
from prospectlens.db import models as m
from prospectlens.pipeline.importer import _upsert, ensure_sport


def sync_config(session: Session, cfg: SportConfig) -> int:
    sport_id = ensure_sport(session, cfg.sport.code, cfg.sport.name_it)
    _upsert(
        session,
        m.MetricDefinition,
        [
            {
                "sport_id": sport_id,
                "code": x.code,
                "name": x.name_it,
                "kind": x.kind,
                "roles": x.roles,
                "higher_is_better": x.higher_is_better,
                "requires": x.requires,
                "formula": x.formula_it,
                "description": x.description_it,
                "how_to_read": x.how_to_read_it,
                "definition": x.model_dump(),
            }
            for x in cfg.metrics
        ],
        ("sport_id", "code"),
        returning=False,
    )
    _upsert(
        session,
        m.GoalDefinition,
        [
            {
                "sport_id": sport_id,
                "code": g.code,
                "letter": g.letter,
                "name": g.name_it,
                "definition": g.model_dump(),
            }
            for g in cfg.goals
        ],
        ("sport_id", "code"),
        returning=False,
    )
    # metriche e lenti tolte dal YAML spariscono anche dal database
    for model, codes in (
        (m.MetricDefinition, [x.code for x in cfg.metrics]),
        (m.GoalDefinition, [g.code for g in cfg.goals]),
    ):
        session.execute(delete(model).where(model.sport_id == sport_id, model.code.not_in(codes)))
    session.commit()
    return sport_id
