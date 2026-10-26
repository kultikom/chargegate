"""Data model and database access."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String,
                        UniqueConstraint)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

import config

engine = create_async_engine(config.DATABASE_URL, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)


def utcnow() -> datetime:
    """All timestamps are stored as naive UTC."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    stations: Mapped[list[Station]] = relationship(back_populates="site")


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # charge box identity from the URL
    name: Mapped[str | None] = mapped_column(String(100))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    ocpp_version: Mapped[str | None] = mapped_column(String(10))
    vendor: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(50))
    serial: Mapped[str | None] = mapped_column(String(50))
    firmware: Mapped[str | None] = mapped_column(String(50))
    remote_addr: Mapped[str | None] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    local_list_pushed: Mapped[datetime | None] = mapped_column(DateTime)
    local_list_status: Mapped[str | None] = mapped_column(String(100))
    site: Mapped[Site | None] = relationship(back_populates="stations")
    connectors: Mapped[list[ConnectorStatus]] = relationship(
        cascade="all, delete-orphan", order_by="ConnectorStatus.connector_id")


class ConnectorStatus(Base):
    __tablename__ = "connector_status"
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True)
    connector_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(50))
    updated: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    energy_wh: Mapped[float | None] = mapped_column(Float)   # last energy register reading
    power_w: Mapped[float | None] = mapped_column(Float)     # last active power reading
    peak_power_w: Mapped[float | None] = mapped_column(Float)  # highest power ever seen (learns 11/22 kW)
    soc: Mapped[float | None] = mapped_column(Float)            # battery state of charge of the car, %
    soc_supported: Mapped[bool | None] = mapped_column(Boolean)  # station has reported SoC at least once

    @property
    def max_power_w(self) -> int:
        """Learned rating of the charging point: 11 kW unless more was ever measured."""
        peak = self.peak_power_w or 0
        if peak <= 11_500:
            return 11_000
        if peak <= 22_500:
            return 22_000
        return int(-(-peak // 1000) * 1000)   # above 22 kW: round up to the next kW


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(200))
    entra_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | entra
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[list[Tag]] = relationship(back_populates="employee", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(40), unique=True)  # normalized: upper case, hex only
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    label: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(10), default="manual")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    employee: Mapped[Employee] = relationship(back_populates="tags")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("station_id", "ocpp_tx_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)  # used as transactionId for OCPP 1.6
    station_id: Mapped[str] = mapped_column(ForeignKey("stations.id", ondelete="CASCADE"))
    connector_id: Mapped[int | None] = mapped_column(Integer)
    ocpp_tx_id: Mapped[str | None] = mapped_column(String(64))  # assigned by the station for 2.0.1
    tag_uid: Mapped[str | None] = mapped_column(String(40))
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime)
    meter_start_wh: Mapped[float | None] = mapped_column(Float)
    meter_last_wh: Mapped[float | None] = mapped_column(Float)
    meter_stop_wh: Mapped[float | None] = mapped_column(Float)
    soc_start: Mapped[float | None] = mapped_column(Float)   # battery %, only if the station reports it
    soc_last: Mapped[float | None] = mapped_column(Float)
    stop_reason: Mapped[str | None] = mapped_column(String(50))
    station: Mapped[Station] = relationship()
    employee: Mapped[Employee | None] = relationship()

    @property
    def energy_kwh(self) -> float | None:
        end = self.meter_stop_wh if self.meter_stop_wh is not None else self.meter_last_wh
        if self.meter_start_wh is None or end is None:
            return None
        return round(max(end - self.meter_start_wh, 0) / 1000, 3)


class AuthEvent(Base):
    __tablename__ = "auth_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    station_id: Mapped[str] = mapped_column(String(64))
    tag_uid: Mapped[str] = mapped_column(String(40), index=True)
    result: Mapped[str] = mapped_column(String(20))  # Accepted | Blocked | Invalid
    reason: Mapped[str | None] = mapped_column(String(100))  # code, see i18n.REASONS
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    employee: Mapped[Employee | None] = relationship()


class SyncState(Base):
    __tablename__ = "sync_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(String(500))


def _add_missing_columns(sync_conn) -> None:
    """Lightweight schema upgrade: add new nullable columns to existing tables.

    create_all() only creates missing tables. New releases only ever add nullable
    columns, so an ALTER TABLE ... ADD COLUMN per missing column is enough.
    """
    from sqlalchemy import inspect
    insp = inspect(sync_conn)
    existing_tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                ddl = col.type.compile(dialect=sync_conn.dialect)
                sync_conn.exec_driver_sql(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl}')


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


# --- Helpers ---------------------------------------------------------

def normalize_uid(raw: str) -> str:
    """Depending on the station, RFID UIDs arrive with colons, spaces or in lower case."""
    return "".join(ch for ch in raw.upper() if ch in "0123456789ABCDEF") or raw.strip().upper()


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
    except ValueError:
        return False
    test = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000)
    return hmac.compare_digest(test.hex(), dk)
