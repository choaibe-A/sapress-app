from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator
from dotenv import dotenv_values

import pandas as pd
import streamlit as st


DB_PATH = Path(__file__).with_name("sapresss_fleet.db")

DATABASE_URL = st.secrets["DATABASE_URL"]

SCHEMA_VERSION = 1


def using_postgres() -> bool:
    return DATABASE_URL.startswith(("postgresql://", "postgres://"))


@contextmanager
def connect() -> Iterator[Any]:
    if using_postgres():
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL is configured through DATABASE_URL, but psycopg is not installed. "
                "Run: pip install -r requirements.txt"
            ) from exc

        conn = psycopg.connect(DATABASE_URL)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with connect() as conn:
        if using_postgres():
            _create_postgres_schema(conn)
            _execute(
                conn,
                """
                INSERT INTO app_meta (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                ("schema_version", str(SCHEMA_VERSION)),
            )
        else:
            _create_sqlite_schema(conn)
            _execute(
                conn,
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

        if _scalar(conn, "SELECT COUNT(*) FROM vehicles") == 0:
            seed_demo_data(conn)


def _create_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_id TEXT PRIMARY KEY,
            plate TEXT NOT NULL,
            driver TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            monthly_objective REAL NOT NULL CHECK (monthly_objective >= 0),
            status TEXT NOT NULL CHECK (status IN ('Actif', 'Maintenance', 'Inactif'))
        );

        CREATE TABLE IF NOT EXISTS routes (
            route_id INTEGER PRIMARY KEY AUTOINCREMENT,
            route_date TEXT NOT NULL,
            vehicle_id TEXT NOT NULL,
            client TEXT NOT NULL,
            route_name TEXT NOT NULL,
            deliveries INTEGER NOT NULL CHECK (deliveries >= 0),
            revenue_ttc REAL NOT NULL CHECK (revenue_ttc >= 0),
            fuel REAL NOT NULL CHECK (fuel >= 0),
            tolls REAL NOT NULL CHECK (tolls >= 0),
            other_costs REAL NOT NULL CHECK (other_costs >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS vehicle_costs (
            cost_id INTEGER PRIMARY KEY AUTOINCREMENT,
            cost_date TEXT NOT NULL,
            vehicle_id TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL CHECK (amount >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT
        );

        CREATE INDEX IF NOT EXISTS idx_routes_date_vehicle
            ON routes(route_date, vehicle_id);
        CREATE INDEX IF NOT EXISTS idx_costs_date_vehicle
            ON vehicle_costs(cost_date, vehicle_id);
        CREATE INDEX IF NOT EXISTS idx_vehicles_status
            ON vehicles(status);
        """
    )


def _create_postgres_schema(conn: Any) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_id TEXT PRIMARY KEY,
            plate TEXT NOT NULL,
            driver TEXT NOT NULL,
            vehicle_type TEXT NOT NULL,
            monthly_objective DOUBLE PRECISION NOT NULL CHECK (monthly_objective >= 0),
            status TEXT NOT NULL CHECK (status IN ('Actif', 'Maintenance', 'Inactif'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS routes (
            route_id BIGSERIAL PRIMARY KEY,
            route_date DATE NOT NULL,
            vehicle_id TEXT NOT NULL REFERENCES vehicles(vehicle_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            client TEXT NOT NULL,
            route_name TEXT NOT NULL,
            deliveries INTEGER NOT NULL CHECK (deliveries >= 0),
            revenue_ttc DOUBLE PRECISION NOT NULL CHECK (revenue_ttc >= 0),
            fuel DOUBLE PRECISION NOT NULL CHECK (fuel >= 0),
            tolls DOUBLE PRECISION NOT NULL CHECK (tolls >= 0),
            other_costs DOUBLE PRECISION NOT NULL CHECK (other_costs >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS vehicle_costs (
            cost_id BIGSERIAL PRIMARY KEY,
            cost_date DATE NOT NULL,
            vehicle_id TEXT NOT NULL REFERENCES vehicles(vehicle_id)
                ON UPDATE CASCADE
                ON DELETE RESTRICT,
            category TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL CHECK (amount >= 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_routes_date_vehicle ON routes(route_date, vehicle_id)",
        "CREATE INDEX IF NOT EXISTS idx_costs_date_vehicle ON vehicle_costs(cost_date, vehicle_id)",
        "CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status)",
    ]
    for statement in statements:
        _execute(conn, statement)


def seed_demo_data(conn: Any) -> None:
    today = date.today()
    vehicles = [
        ("SAP-CASA-01", "45231-A-6", "Y. Amrani", "Utilitaire 12m3", 58_000, "Actif"),
        ("SAP-RABAT-02", "39118-B-1", "N. Bennani", "Fourgon distribution", 42_000, "Actif"),
        ("SAP-MARR-03", "77405-D-8", "K. El Fassi", "Camion leger", 64_000, "Actif"),
        ("SAP-TANGER-04", "66290-J-9", "S. El Idrissi", "Pick-up", 36_000, "Maintenance"),
    ]
    routes = [
        (today - timedelta(days=26), "SAP-CASA-01", "Agence Casablanca Centre", "Casablanca -> Mohammedia -> Rabat", 186, 15_800, 1_180, 210, 320),
        (today - timedelta(days=22), "SAP-RABAT-02", "Agence Rabat Agdal", "Rabat -> Sale -> Kenitra", 142, 11_200, 760, 95, 180),
        (today - timedelta(days=19), "SAP-MARR-03", "Depot Marrakech", "Marrakech -> Benguerir -> Safi", 214, 18_900, 1_560, 260, 410),
        (today - timedelta(days=14), "SAP-CASA-01", "Presse nationale", "Casablanca -> El Jadida", 165, 13_600, 980, 120, 260),
        (today - timedelta(days=11), "SAP-TANGER-04", "Agence Tanger", "Tanger -> Tetouan", 88, 7_400, 640, 70, 150),
        (today - timedelta(days=7), "SAP-RABAT-02", "Abonnements entreprises", "Rabat -> Temara -> Skhirat", 119, 9_850, 690, 55, 170),
        (today - timedelta(days=3), "SAP-MARR-03", "Edition Sud", "Marrakech -> Agadir", 238, 21_500, 1_920, 310, 520),
        (today - timedelta(days=1), "SAP-CASA-01", "Kiosques Grand Casablanca", "Casablanca -> Bouskoura -> Nouaceur", 204, 17_300, 1_120, 80, 300),
    ]
    costs = [
        (today - timedelta(days=25), "SAP-CASA-01", "Entretien", 2_400),
        (today - timedelta(days=20), "SAP-RABAT-02", "Reparation", 1_750),
        (today - timedelta(days=17), "SAP-MARR-03", "Entretien", 3_100),
        (today - timedelta(days=10), "SAP-TANGER-04", "Reparation", 4_600),
        (today - timedelta(days=5), "SAP-CASA-01", "Assurance", 1_850),
        (today - timedelta(days=2), "SAP-MARR-03", "Pneus", 5_200),
    ]

    placeholders = "%s" if using_postgres() else "?"
    vehicle_sql = f"""
        INSERT INTO vehicles
            (vehicle_id, plate, driver, vehicle_type, monthly_objective, status)
        VALUES ({placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders})
    """
    route_sql = f"""
        INSERT INTO routes
            (route_date, vehicle_id, client, route_name, deliveries, revenue_ttc, fuel, tolls, other_costs)
        VALUES ({placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders}, {placeholders})
    """
    cost_sql = f"""
        INSERT INTO vehicle_costs (cost_date, vehicle_id, category, amount)
        VALUES ({placeholders}, {placeholders}, {placeholders}, {placeholders})
    """

    _execute_many(conn, vehicle_sql, vehicles)
    _execute_many(conn, route_sql, [_serialize_dates(row) for row in routes])
    _execute_many(conn, cost_sql, [_serialize_dates(row) for row in costs])


def _serialize_dates(values: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(value.isoformat() if isinstance(value, date) else value for value in values)


def _execute(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> None:
    if isinstance(conn, sqlite3.Connection):
        conn.execute(sql, params or ())
    else:
        with conn.cursor() as cur:
            cur.execute(sql, params)


def _execute_many(conn: Any, sql: str, rows: list[tuple[Any, ...]]) -> None:
    if isinstance(conn, sqlite3.Connection):
        conn.executemany(sql, rows)
    else:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)


def _scalar(conn: Any, sql: str) -> Any:
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(sql).fetchone()[0]
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


def read_vehicles() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                vehicle_id,
                plate,
                driver,
                vehicle_type AS type,
                monthly_objective AS objective,
                status
            FROM vehicles
            ORDER BY vehicle_id
            """,
            conn,
        )


def read_routes() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                route_id,
                route_date AS date,
                vehicle_id,
                client,
                route_name AS route,
                deliveries,
                revenue_ttc,
                fuel,
                tolls,
                other_costs
            FROM routes
            ORDER BY route_date DESC, route_id DESC
            """,
            conn,
            parse_dates=["date"],
        )


def read_costs() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query(
            """
            SELECT
                cost_id,
                cost_date AS date,
                vehicle_id,
                category,
                amount
            FROM vehicle_costs
            ORDER BY cost_date DESC, cost_id DESC
            """,
            conn,
            parse_dates=["date"],
        )


def add_route(
    route_date: date,
    vehicle_id: str,
    client: str,
    route_name: str,
    deliveries: int,
    revenue_ttc: float,
    fuel: float,
    tolls: float,
    other_costs: float,
) -> None:
    placeholder = "%s" if using_postgres() else "?"
    sql = f"""
        INSERT INTO routes
            (route_date, vehicle_id, client, route_name, deliveries, revenue_ttc, fuel, tolls, other_costs)
        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
    """
    with connect() as conn:
        _execute(
            conn,
            sql,
            (
                route_date.isoformat(),
                vehicle_id,
                client,
                route_name,
                deliveries,
                revenue_ttc,
                fuel,
                tolls,
                other_costs,
            ),
        )


def add_vehicle_cost(cost_date: date, vehicle_id: str, category: str, amount: float) -> None:
    placeholder = "%s" if using_postgres() else "?"
    sql = f"""
        INSERT INTO vehicle_costs (cost_date, vehicle_id, category, amount)
        VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})
    """
    with connect() as conn:
        _execute(conn, sql, (cost_date.isoformat(), vehicle_id, category, amount))
