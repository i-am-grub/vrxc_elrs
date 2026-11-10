"""
Decoding of the video channel carried by MSP_SET_VTX_CONFIG
"""

from typing import Optional

# Standard VTX table order (Betaflight / ExpressLRS backpack): 8 channels per band
BANDS = "ABEFRL"

FREQUENCIES = {
    "A": (5865, 5845, 5825, 5805, 5785, 5765, 5745, 5725),
    "B": (5733, 5752, 5771, 5790, 5809, 5828, 5847, 5866),
    "E": (5705, 5685, 5665, 5645, 5885, 5905, 5925, 5945),
    "F": (5740, 5760, 5780, 5800, 5820, 5840, 5860, 5880),
    "R": (5658, 5695, 5732, 5769, 5806, 5843, 5880, 5917),
    "L": (5362, 5399, 5436, 5473, 5510, 5547, 5584, 5621),
}

# MSP_SET_VTX_CONFIG: values up to this are a VTX table index,
# anything above is a frequency in MHz
INDEX_MAX = 63


def decode_vtx_config(
    payload: bytes,
) -> Optional[tuple[Optional[str], Optional[int], int]]:
    """
    Gets the channel from a MSP_SET_VTX_CONFIG payload

    :param payload: The packet payload, starting with a little-endian
    16 bit channel index or frequency
    :return: (band letter, channel 1-8, frequency in MHz). The band and
    channel are None for a frequency outside the standard table.
    None if the payload does not hold a usable channel.
    """
    if len(payload) < 2:
        return None

    value = int.from_bytes(payload[0:2], "little")

    if value <= INDEX_MAX:
        if value >= len(BANDS) * 8:
            return None

        band = BANDS[value // 8]
        channel = value % 8 + 1
        return band, channel, FREQUENCIES[band][channel - 1]

    if not 5000 <= value <= 6100:
        return None

    # A few frequencies exist in two bands (5880: F8 and R7): prefer Raceband
    for band in "RFABEL":
        if value in FREQUENCIES[band]:
            return band, FREQUENCIES[band].index(value) + 1, value

    return None, None, value
