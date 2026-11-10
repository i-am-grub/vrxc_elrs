"""
Which video channel each pilot should receive from RotorHazard
"""

import json
from typing import Optional

from .vtx import BANDS, FREQUENCIES

NO_PILOT = 0


def vtx_index(band: Optional[str], channel: Optional[int], frequency: int) -> Optional[int]:
    """
    Gets the standard VTX table index (0-47) of a channel, the value the
    goggles' and radio's backpack understand

    :param band: Band letter of the frequency set, if any
    :param channel: Channel 1-8 of the frequency set, if any
    :param frequency: Frequency in MHz
    :return: The index, or None when the channel is not in the table
    """
    if isinstance(band, str) and len(band) == 1 and band in BANDS and isinstance(channel, int) and 1 <= channel <= 8:
        if FREQUENCIES[band][channel - 1] == frequency:
            return BANDS.index(band) * 8 + channel - 1

    # Band and channel missing or out of date: find the frequency in the table,
    # preferring Raceband where a frequency exists in two bands
    for band in "RFABEL":
        if frequency in FREQUENCIES[band]:
            return BANDS.index(band) * 8 + FREQUENCIES[band].index(frequency)

    return None


def node_frequencies(rhapi) -> list[tuple[Optional[str], Optional[int], int]]:
    """
    Gets (band, channel, frequency) of every node in the active frequency set
    """
    freqs = json.loads(rhapi.race.frequencyset.frequencies)
    return list(zip(freqs["b"], freqs["c"], freqs["f"]))


def index_for_node(
    frequencies: list[tuple[Optional[str], Optional[int], int]], node_index: Optional[int]
) -> Optional[int]:
    """
    Gets the VTX table index a node is set to

    :return: None if the node has no frequency or one outside the table
    """
    if node_index is None or not 0 <= node_index < len(frequencies):
        return None

    band, channel, frequency = frequencies[node_index]
    if not frequency:
        return None

    return vtx_index(band, channel, frequency)


def current_assignments(rhapi) -> dict[int, Optional[int]]:
    """
    Pilots of the race about to be played, with their node
    """
    return {
        pilot_id: node_index
        for node_index, pilot_id in rhapi.race.pilots.items()
        if pilot_id and pilot_id != NO_PILOT
    }


def upcoming_heat_ids(rhapi) -> list[int]:
    """
    The heat about to be played, then the planned heats that have not been raced yet
    in the order RotorHazard lists them
    """
    class_orders: dict[int, int] = {}

    def class_order(heat) -> int:
        if not heat.class_id:
            return 0
        if heat.class_id not in class_orders:
            raceclass = rhapi.db.raceclass_by_id(heat.class_id)
            class_orders[heat.class_id] = getattr(raceclass, "order", 0) or 0
        return class_orders[heat.class_id]

    heats = [
        heat
        for heat in rhapi.db.heats
        if heat.active and rhapi.db.heat_max_round(heat.id) == 0
    ]
    heats.sort(key=lambda heat: (class_order(heat), heat.order or 0, heat.id))

    ids = [heat.id for heat in heats]

    current = rhapi.race.heat
    if current:
        ids = [current] + [id_ for id_ in ids if id_ != current]

    return ids


def upcoming_assignments(rhapi) -> dict[int, Optional[int]]:
    """
    For every pilot in the heat about to be played or in a planned heat, the node
    of the first of those heats they race in. The node is None when that heat
    assigns frequencies automatically, so a later heat is never used instead.
    """
    assignments: dict[int, Optional[int]] = {}

    for heat_id in upcoming_heat_ids(rhapi):
        for slot in rhapi.db.slots_by_heat(heat_id):
            if slot.pilot_id and slot.pilot_id != NO_PILOT:
                if slot.pilot_id not in assignments:
                    assignments[slot.pilot_id] = slot.node_index

    return assignments
