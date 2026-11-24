"""The UKPN GSP name crosswalk (see docs/PROFILE.md for the evidence)."""

from pipeline.adapters.ukpn import match_gsp

OVERVIEW = {"BARKING C (EPN)", "BARKING WEST (EPN)", "ELSTREE", "CANTERBURY NORTH",
            "WILLESDEN 132", "WILLESDEN 66", "WIMBLEDON 1&2", "HURST (SPN)", "HURST (LPN)"}


def test_plain_and_suffixed_names():
    assert match_gsp("Barking West 33kV", "EPN", OVERVIEW) == "BARKING WEST (EPN)"
    assert match_gsp("Wimbledon 1&2 132kV", "LPN", OVERVIEW) == "WIMBLEDON 1&2"
    assert match_gsp("Hurst", "SPN", OVERVIEW) == "HURST (SPN)"


def test_aliases():
    assert match_gsp("Canterbury", "SPN", OVERVIEW) == "CANTERBURY NORTH"
    assert match_gsp("Barking 132kV", "EPN", OVERVIEW) == "BARKING C (EPN)"
    assert match_gsp("Elstree Stanmore", "EPN", OVERVIEW) == "ELSTREE"
    assert match_gsp("Willesden Grid 66 kV", "LPN", OVERVIEW) == "WILLESDEN 66"


def test_willesden_epn_stays_unmapped():
    assert match_gsp("Willesden", "EPN", OVERVIEW) is None
