from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True)
class TrackPoint:
    lat: float
    lon: float
    ele: float | None = None
    time: str | None = None

    def to_dict(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "ele": self.ele,
            "time": self.time,
        }


def parse_gpx_track_points(content: bytes) -> list[TrackPoint]:
    root = ET.fromstring(content)
    points: list[TrackPoint] = []

    for element in root.iter():
        if _local_name(element.tag) != "trkpt":
            continue

        lat_raw = element.attrib.get("lat")
        lon_raw = element.attrib.get("lon")
        if lat_raw is None or lon_raw is None:
            continue

        ele = None
        time = None
        for child in element:
            name = _local_name(child.tag)
            if name == "ele" and child.text:
                ele = float(child.text)
            elif name == "time" and child.text:
                time = child.text

        points.append(TrackPoint(lat=float(lat_raw), lon=float(lon_raw), ele=ele, time=time))

    if not points:
        raise ValueError("GPX file does not contain track points")
    return points


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
