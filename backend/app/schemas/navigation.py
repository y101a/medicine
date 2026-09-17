from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NearbyHospitalsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    latitude: float
    longitude: float
    location_consent: bool = Field(alias="locationConsent")
    route_mode: Literal["driving", "walking"] = Field(default="driving", alias="routeMode")


class AreaHospitalsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = Field(min_length=2, max_length=12)

    @field_validator("city", mode="before")
    @classmethod
    def trim_city(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class HospitalNavigationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    poi_id: str | None = Field(default=None, serialization_alias="poiId")
    name: str
    address: str | None = None
    telephone: str | None = None
    district: str | None = None
    straight_distance_meters: int | None = Field(
        default=None,
        serialization_alias="straightDistanceMeters",
    )
    route_distance_meters: int | None = Field(
        default=None,
        serialization_alias="routeDistanceMeters",
    )
    route_duration_seconds: int | None = Field(
        default=None,
        serialization_alias="routeDurationSeconds",
    )
    route_mode: str | None = Field(default=None, serialization_alias="routeMode")
    navigation_url: str = Field(serialization_alias="navigationUrl")


class HospitalNavigationResponse(BaseModel):
    mode: Literal["nearby", "area"]
    route_mode: str | None = Field(default=None, serialization_alias="routeMode")
    count: int
    items: list[HospitalNavigationOut]
    notice: str

