from datetime import date
from pathlib import Path

from prospectlens.providers.base import CompetitionRec, SeasonRec
from prospectlens.providers.csv_import import CsvImportProvider, load_mapping
from tests.conftest import CONFIG_DIR

SAMPLE = Path(__file__).parent / "data" / "wyscout_sample.csv"


def test_csv_mapping_and_per90_conversion() -> None:
    mapping = load_mapping(CONFIG_DIR / "csv" / "wyscout.yaml")
    comp = CompetitionRec("serie-d-a", "Serie D", "IT", 4, "A")
    season = SeasonRec("2024-25", date(2024, 7, 1), date(2025, 6, 30))
    [b] = list(CsvImportProvider(SAMPLE, mapping, comp, season).bundles())

    assert len(b.players) == 2  # la riga senza nome è saltata
    left_back, striker = b.players
    assert left_back.primary_position == "FB" and left_back.secondary_positions == ("FB",)
    assert left_back.birth_date == date(2004, 3, 12) and left_back.foot == "left"
    assert striker.nationalities == ("IT",)  # paese non mappato ignorato
    assert striker.birth_date is not None and striker.birth_date.year == 2004  # da età 20

    stats = {s.player_ext: s for s in b.stats}
    lb = stats[left_back.ext_id]
    assert lb.minutes == 2430 and lb.stats["goals"] == 1
    assert lb.stats["key_passes"] == 32.4  # 1,2 per 90 x 27 partite intere
    assert b.squad[0].status == "loan" and b.squad[0].contract_until == date(2026, 6, 30)
    assert [v.value_eur for v in b.market_values] == [150000]
    assert b.data_types == {"player_stats_basic", "player_stats_advanced", "market_values"}

    # ID stabili: stesso file, stessi ID
    [again] = list(CsvImportProvider(SAMPLE, mapping, comp, season).bundles())
    assert [p.ext_id for p in again.players] == [p.ext_id for p in b.players]
