

import json
import logging
from dataclasses import dataclass, field, fields
from enum import Enum, auto
from typing import NamedTuple, Self, TypedDict

import .bp_utils

logger = logging.getLogger(__name__)


class _CanvasSpec(NamedTuple):
    rows: int
    cols: int


class CanvasSpecs(_CanvasSpec, Enum):
    """
    Canvas specs built into the plugin
    """

    HDZERO_GOGGLE = 18, 50


class ElementAlignment(Enum):
    """
    Alignment of element on canvas
    """

    CANVAS_LEFT = auto()
    """Left align text on canvas"""
    CANVAS_CENTER = auto()
    """Center text on canvas"""
    CANVAS_RIGHT = auto()
    """Right align text at specificed point"""
    POINT_LEFT = auto()
    """Left align text at specificed point"""
    POINT_CENTER = auto()
    """Center text at specificed point"""
    POINT_RIGHT = auto()
    """Right align text at specificed point"""


class OSDElementDataDict(TypedDict):
    """
    An OSD element dictionary data structure.

    This is currently used to represent the FPVScores
    data structure.
    """

    row: int
    col: int
    hold_secs: int
    center: bool
    enabled: bool


class OSDDataDict(TypedDict):
    """
    A dictionary data structure of OSD elements.

    This is currently used to represent the FPVScores
    data structure.
    """

    heat_name: OSDElementDataDict
    class_name: OSDElementDataDict
    event_name: OSDElementDataDict
    announcement: OSDElementDataDict
    race_status: OSDElementDataDict
    lap_position: OSDElementDataDict
    lap_result: OSDElementDataDict
    gap_result: OSDElementDataDict
    gap_behind: OSDElementDataDict
    recent_laps: OSDElementDataDict
    results: OSDElementDataDict


class OSDPilotDataDict(TypedDict):
    """
    A dictionary data structure of OSD data for a single
    pilot.

    This is currently used to represent the FPVScores
    data structure.
    """

    version: int
    elements: OSDDataDict


@dataclass(frozen=True, slots=True)
class ElementOSD:
    """
    An OSD element data structure
    """

    row: int = 0
    col: int = 0
    uptime: int = 3
    alignment: ElementAlignment = ElementAlignment.CANVAS_CENTER
    enabled: bool = False

    def __post_init__(self):
        """
        Post initalization validation
        """
        if not all(
            [
                isinstance(self.row, int),
                isinstance(self.col, int),
                isinstance(self.alignment, ElementAlignment),
                isinstance(self.enabled, bool),
            ]
        ):
            msg = f"OSD element data did not have the correct typing: {self}"
            raise TypeError(msg)

    @classmethod
    def from_fpvscores(cls, data: OSDElementDataDict) -> Self:
        """
        Parse the dictionary data into a dataclass

        Raises:
            KeyError: _description_
        """
        if data["center"] is True:
            alignment = ElementAlignment.CANVAS_CENTER
        else:
            alignment = ElementAlignment.POINT_LEFT

        return cls(
            row=data["row"],
            col=data["col"],
            alignment=alignment,
            enabled=data["enabled"],
        )





@dataclass(frozen=True, slots=True)
class PilotOSDElements:
    """
    Internal data structure for mapping all OSD elements
    """

    heat_name: ElementOSD = field(default_factory=ElementOSD)
    class_name: ElementOSD = field(default_factory=ElementOSD)
    event_name: ElementOSD = field(default_factory=ElementOSD)
    announcement: ElementOSD = field(default_factory=ElementOSD)
    race_status: ElementOSD = field(default_factory=ElementOSD)
    lap_position: ElementOSD = field(default_factory=ElementOSD)
    lap_result: ElementOSD = field(default_factory=ElementOSD)
    gap_result: ElementOSD = field(default_factory=ElementOSD)
    gap_behind: ElementOSD = field(default_factory=ElementOSD)
    recent_laps: ElementOSD = field(default_factory=ElementOSD)
    results: ElementOSD = field(default_factory=ElementOSD)

    @classmethod
    def from_fpvscores(cls, elements: OSDDataDict) -> Self:
        """
        Parse the dictionary data into a dataclass

        Raises:
            KeyError: _description_
        """
        fields_data: dict[str, ElementOSD] = {}

        for field_ in fields(PilotOSDElements):
            if field_.name in elements:
                element = elements[field_.name]
            else:
                continue

            try:
                ele = ElementOSD.from_fpvscores(element)
            except KeyError:
                msg = "Missing data in OSD element structure: %s"
                logger.warning(msg, elements)
                continue
            except TypeError:
                msg = (
                    "Elements in data structure (%s) failed validation. "
                    "Defaulting to global settings."
                )
                logger.warning(msg, element)
                continue

            fields_data[field_.name] = ele

        return cls(**fields_data)

    @classmethod
    def from_global_attributes(cls, rhapi) -> Self:
        racestart_uptime = rhapi.db.option("_racestart_uptime")
        finish_uptime = rhapi.db.option("_finish_uptime")
        results_uptime = rhapi.db.option("_results_uptime")
        announcement_uptime = rhapi.db.option("_announcement_uptime")

        heatname_row = rhapi.db.option("_heatname_row")
        classname_row = rhapi.db.option("_classname_row")
        event_name_row = rhapi.db.option("_eventname_row")
        announcement_row = rhapi.db.option("_announcement_row")
        status_row = rhapi.db.option("_status_row")
        currentlap_row = rhapi.db.option("_currentlap_row")
        lapresults_row = rhapi.db.option("_lapresults_row")
        results_row = rhapi.db.option("_results_row")

        use_heat_name = bp_utils.process_bool_attr(rhapi.db.option("_heat_name"))
        use_round_num = bp_utils.process_bool_attr(rhapi.db.option("_round_num"))
        use_class_name = bp_utils.process_bool_attr(rhapi.db.option("_class_name"))
        use_event_name = bp_utils.process_bool_attr(rhapi.db.option("_event_name"))
        use_position_mode = bp_utils.process_bool_attr(rhapi.db.option("_position_mode"))
        use_gap_mode = bp_utils.process_bool_attr(rhapi.db.option("_gap_mode"))
        use_results_mode = bp_utils.process_bool_attr(rhapi.db.option("_results_mode"))

        heat_name = ElementOSD(row=heatname_row, col=0, enabled=use_heat_name)
        class_name = ElementOSD(row=classname_row, col=0, enabled=use_class_name)
        event_name = ElementOSD(row=event_name_row, col=0, enabled=use_event_name)
        announcement = ElementOSD(row=announcement_row, col=0, enabled=True)
        race_status = ElementOSD(row=status_row, col=0, enabled=True)
        lap_position = ElementOSD()
        lap_result = ElementOSD()
        gap_result = ElementOSD()
        gap_behind = ElementOSD()
        recent_laps = ElementOSD()
        results = ElementOSD(row=results_row, col=0, enabled=use_results_mode)

        return cls(
            heat_name=heat_name,
            class_name=class_name,
            event_name=event_name,
            announcement=announcement,
            race_status=race_status,
            lap_position=lap_position,
            lap_result=lap_result,
            gap_result=gap_result,
            gap_behind=gap_behind,
            recent_laps=recent_laps,
            results=results,
        )


@dataclass(frozen=True, slots=True)
class PilotOSD:
    """Internal data strucutre for a pilot's"""

    elements: PilotOSDElements
    hardware: CanvasSpecs = CanvasSpecs.HDZERO_GOGGLE

    def __post_init__(self):
        for element in fields(PilotOSDElements):
            value: ElementOSD | None = getattr(self.elements, element.name)
            if value is not None:
                if value.col >= self.hardware.cols:
                    msg = "Element column exceeds the number of columns on the canvas"
                    raise ValueError(msg)
                if value.row >= self.hardware.rows:
                    msg = "Element row exceeds the number of rows on the canvas"
                    raise ValueError(msg)

    @classmethod
    def from_fpvscores(cls, attribute_data: str | bytes | bytearray) -> Self:
        """
        Generate OSD data for a pilot from the FPVScores data structure

        Args:
            attribute_data: The data to parse

        Raises:
            JSONDecodeError: Unable to parse the data as JSON
            KeyError: Stored data structure had missing data
            TypeError: When element type validation fails

        """
        osd_data: OSDPilotDataDict = json.loads(attribute_data)
        elements = osd_data["elements"]
        return cls(elements=PilotOSDElements.from_fpvscores(elements))

    @classmethod
    def from_global_attributes(cls, rhapi) -> Self:
        """
        Global OSD settings stored in the database
        """
        return cls(elements=PilotOSDElements.from_global_attributes(rhapi))


@dataclass(frozen=True, slots=True)
class OSDRaceMessages:
    """
    Data structure for race messages
    """

    racestage: str
    racestart: str
    pilotdone: str
    racefinish: str
    racestop: str
    leader: str

    @classmethod
    def from_global_attribute(cls, rhapi) -> Self:
        racestage: str = rhapi.db.option("_racestage_message")
        racestart: str = rhapi.db.option("_racestart_message")
        pilotdone: str = rhapi.db.option("_pilotdone_message")
        racefinish: str = rhapi.db.option("_racefinish_message")
        racestop: str = rhapi.db.option("_racestop_message")
        leader: str = rhapi.db.option("_leader_message")

        return cls(
            racestage=racestage,
            racestart=racestart,
            pilotdone=pilotdone,
            racefinish=racefinish,
            racestop=racestop,
            leader=leader,
        )


@dataclass(frozen=True, slots=True)
class OSDMessageUptimeDuration:
    """
    Data structure for uptime durations
    """

    racestart: int
    finish: int
    results: int
    announcement: int

    @classmethod
    def from_global_attribute(cls, rhapi) -> Self:
        racestart = rhapi.db.option("_racestart_uptime") * 1e-1
        finish = rhapi.db.option("_finish_uptime") * 1e-1
        results = rhapi.db.option("_results_uptime") * 1e-1
        announcement = rhapi.db.option("_racestart_uptime") * 1e-1

        return cls(
            racestart=racestart,
            finish=finish,
            results=results,
            announcement=announcement,
        )
