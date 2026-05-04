from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Station(TimestampMixin, Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    location: Mapped[str | None] = mapped_column(String(255))
    scanner_host: Mapped[str | None] = mapped_column(String(255))
    scanner_port: Mapped[int | None]
    scanner_protocol: Mapped[str | None] = mapped_column(String(80))
    workflow_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        server_default="measurement_capture",
    )
    workflow_title: Mapped[str | None] = mapped_column(String(120))
    workflow_config: Mapped[dict[str, object] | None] = mapped_column(JSON)
    adapter_config: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    payload_format: Mapped[str | None] = mapped_column(Text)
    timing_notes: Mapped[str | None] = mapped_column(Text)
    network_notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    measurements: Mapped[list["Measurement"]] = relationship(back_populates="station")
    raw_payloads: Mapped[list["RawPayload"]] = relationship(back_populates="station")
    heartbeats: Mapped[list["StationHeartbeat"]] = relationship(back_populates="station")
    events: Mapped[list["StationEvent"]] = relationship(back_populates="station")
    measurement_type_links: Mapped[list["StationMeasurementType"]] = relationship(
        back_populates="station",
        cascade="all, delete-orphan",
    )


class Part(TimestampMixin, Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    rueckmeldenummer: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    measurements: Mapped[list["Measurement"]] = relationship(back_populates="part")


class RawPayload(Base):
    __tablename__ = "raw_payloads"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    station_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stations.id"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    station: Mapped[Station] = relationship(back_populates="raw_payloads")
    measurements: Mapped[list["Measurement"]] = relationship(back_populates="raw_payload")


class StationHeartbeat(Base):
    __tablename__ = "station_heartbeats"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    station_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stations.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    companion_version: Mapped[str | None] = mapped_column(String(80))
    adapter_status: Mapped[dict[str, object] | None] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    station: Mapped[Station] = relationship(back_populates="heartbeats")


class StationEvent(Base):
    __tablename__ = "station_events"
    __table_args__ = (
        Index("ix_station_events_station_occurred", "station_id", "occurred_at"),
        Index("ix_station_events_severity", "severity"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    station_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stations.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, object] | None] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    station: Mapped[Station] = relationship(back_populates="events")


class MeasurementType(Base):
    __tablename__ = "measurement_types"

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    station_links: Mapped[list["StationMeasurementType"]] = relationship(
        back_populates="measurement_type",
        cascade="all, delete-orphan",
    )
    values: Mapped[list["MeasurementValue"]] = relationship(back_populates="type_definition")


class StationMeasurementType(Base):
    __tablename__ = "station_measurement_types"

    station_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stations.id"), primary_key=True
    )
    measurement_type_code: Mapped[str] = mapped_column(
        String(80), ForeignKey("measurement_types.code"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    station: Mapped[Station] = relationship(back_populates="measurement_type_links")
    measurement_type: Mapped[MeasurementType] = relationship(back_populates="station_links")


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint(
            "station_id",
            "idempotency_key",
            name="uq_measurements_station_idempotency",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    part_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("parts.id"), nullable=False)
    station_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stations.id"), nullable=False
    )
    result_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_payload_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("raw_payloads.id")
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    part: Mapped[Part] = relationship(back_populates="measurements")
    station: Mapped[Station] = relationship(back_populates="measurements")
    raw_payload: Mapped[RawPayload | None] = relationship(back_populates="measurements")
    values: Mapped[list["MeasurementValue"]] = relationship(
        back_populates="measurement",
        cascade="all, delete-orphan",
    )


class MeasurementValue(Base):
    __tablename__ = "measurement_values"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    measurement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("measurements.id"), nullable=False
    )
    measurement_type: Mapped[str] = mapped_column(
        String(80), ForeignKey("measurement_types.code"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40))
    result_status: Mapped[str | None] = mapped_column(String(40))

    measurement: Mapped[Measurement] = relationship(back_populates="values")
    type_definition: Mapped[MeasurementType] = relationship(back_populates="values")
