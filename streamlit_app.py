import streamlit as st

from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import database


VAT_RATE = 0.20
BONUS_RATE = 0.025


st.set_page_config(
    page_title="Sapresss - Suivi flotte",
    page_icon=":material/local_shipping:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def mad(value: float) -> str:
    return f"{value:,.0f} MAD".replace(",", " ")


def compact_mad(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.2f} M MAD"
    if abs_value >= 1_000:
        return f"{value / 1_000:.0f} k MAD"
    return mad(value)


def pct(value: float) -> str:
    return f"{value:.1f}%"


def enrich_missions(missions: pd.DataFrame) -> pd.DataFrame:
    data = missions.copy()
    data["date"] = pd.to_datetime(data["date"]).dt.date
    data["revenue_ht"] = data["revenue_ttc"] / (1 + VAT_RATE)
    data["vat"] = data["revenue_ttc"] - data["revenue_ht"]
    data["variable_costs"] = data["fuel"] + data["tolls"] + data["other_costs"]
    data["gross_profit"] = data["revenue_ht"] - data["variable_costs"]
    data["driver_bonus"] = data["gross_profit"].clip(lower=0) * BONUS_RATE
    data["net_profit_before_fixed"] = data["gross_profit"] - data["driver_bonus"]
    return data


def vehicle_summary(
    missions: pd.DataFrame, fixed_costs: pd.DataFrame, vehicles: pd.DataFrame
) -> pd.DataFrame:
    mission_totals = (
        missions.groupby("vehicle_id", as_index=False)
        .agg(
            missions=("vehicle_id", "size"),
            revenue_ttc=("revenue_ttc", "sum"),
            deliveries=("deliveries", "sum"),
            revenue_ht=("revenue_ht", "sum"),
            vat=("vat", "sum"),
            fuel=("fuel", "sum"),
            tolls=("tolls", "sum"),
            other_costs=("other_costs", "sum"),
            variable_costs=("variable_costs", "sum"),
            driver_bonus=("driver_bonus", "sum"),
            profit_before_fixed=("net_profit_before_fixed", "sum"),
        )
    )

    fixed_totals = (
        fixed_costs.groupby("vehicle_id", as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "fixed_costs"})
    )

    summary = (
        vehicles.merge(mission_totals, on="vehicle_id", how="left")
        .merge(fixed_totals, on="vehicle_id", how="left")
        .fillna(0)
    )
    summary["net_profit"] = summary["profit_before_fixed"] - summary["fixed_costs"]
    summary["margin"] = (summary["net_profit"] / summary["revenue_ht"]).where(summary["revenue_ht"] > 0, 0) * 100
    summary["objective_progress"] = (summary["revenue_ttc"] / summary["objective"]).where(
        summary["objective"] > 0, 0
    ) * 100
    return summary


def add_mission_form() -> None:
    vehicles = database.read_vehicles()
    with st.form("mission_form", clear_on_submit=True):
        cols = st.columns(4)
        mission_date = cols[0].date_input("Date", value=date.today())
        vehicle_id = cols[1].selectbox("Vehicule", vehicles["vehicle_id"].tolist())
        client = cols[2].text_input("Client", placeholder="Nom du client")
        route = cols[3].text_input("Tournee", placeholder="Casablanca -> Rabat")

        cols = st.columns(5)
        deliveries = cols[0].number_input("Livraisons", min_value=0, step=1, value=120)
        revenue_ttc = cols[1].number_input("CA TTC", min_value=0, step=500, value=10_000)
        fuel = cols[2].number_input("Carburant", min_value=0, step=100, value=750)
        tolls = cols[3].number_input("Peages", min_value=0, step=50, value=100)
        other_costs = cols[4].number_input("Autres frais", min_value=0, step=50, value=200)

        submitted = st.form_submit_button("Ajouter la tournee", use_container_width=True)
        if submitted:
            database.add_route(
                mission_date,
                vehicle_id,
                client or "Client non renseigne",
                route or "Tournee non renseignee",
                deliveries,
                revenue_ttc,
                fuel,
                tolls,
                other_costs,
            )
            st.success("Tournee ajoutee.")
            st.rerun()


def add_cost_form() -> None:
    vehicles = database.read_vehicles()
    with st.form("cost_form", clear_on_submit=True):
        cols = st.columns(4)
        cost_date = cols[0].date_input("Date de la charge", value=date.today())
        vehicle_id = cols[1].selectbox("Vehicule concerne", vehicles["vehicle_id"].tolist())
        category = cols[2].selectbox("Categorie", ["Entretien", "Reparation", "Pneus", "Assurance", "Amendes", "Autre"])
        amount = cols[3].number_input("Montant", min_value=0, step=100, value=1_000)

        submitted = st.form_submit_button("Ajouter la charge", use_container_width=True)
        if submitted:
            database.add_vehicle_cost(cost_date, vehicle_id, category, amount)
            st.success("Charge ajoutee.")
            st.rerun()


def render_metric(label: str, value: str, delta: str | None = None) -> None:
    st.metric(label=label, value=value, delta=delta)


database.init_db()

st.markdown(
    """
    <style>
    .block-container {padding-top: 1.5rem;}
    div[data-testid="stMetric"] {
        border: 1px solid rgba(128, 128, 128, .24);
        border-radius: 8px;
        padding: 14px 16px;
        background: rgba(128, 128, 128, .08);
    }
    div[data-testid="stMetricLabel"] p {font-size: .85rem;}
    div[data-testid="stMetricValue"] {
        font-size: 1.55rem;
        line-height: 1.2;
        white-space: normal;
    }
    .status-pill {
        display: inline-block;
        border-radius: 999px;
        padding: 3px 9px;
        font-size: 12px;
        border: 1px solid #d1d5db;
        color: #374151;
        background: #f9fafb;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

vehicles = database.read_vehicles()
missions = enrich_missions(database.read_routes())
fixed_costs = database.read_costs()
fixed_costs["date"] = pd.to_datetime(fixed_costs["date"]).dt.date

st.sidebar.title("Filtres")
min_date = min(missions["date"].min(), fixed_costs["date"].min())
max_date = max(missions["date"].max(), fixed_costs["date"].max())
date_range = st.sidebar.date_input("Periode", value=(min_date, max_date))
selected_status = st.sidebar.multiselect(
    "Statut vehicule",
    options=vehicles["status"].unique().tolist(),
    default=vehicles["status"].unique().tolist(),
)
selected_vehicles = st.sidebar.multiselect(
    "Vehicules",
    options=vehicles["vehicle_id"].tolist(),
    default=vehicles["vehicle_id"].tolist(),
)

if len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

vehicles = vehicles[
    vehicles["status"].isin(selected_status) & vehicles["vehicle_id"].isin(selected_vehicles)
]
missions = missions[
    (missions["date"] >= start_date)
    & (missions["date"] <= end_date)
    & (missions["vehicle_id"].isin(vehicles["vehicle_id"]))
]
fixed_costs = fixed_costs[
    (fixed_costs["date"] >= start_date)
    & (fixed_costs["date"] <= end_date)
    & (fixed_costs["vehicle_id"].isin(vehicles["vehicle_id"]))
]

summary = vehicle_summary(missions, fixed_costs, vehicles)

st.title("Sapresss - tableau de bord flotte")
st.caption("Suivi des tournees, livraisons, TVA 20%, charges vehicules, primes chauffeur et objectifs en MAD.")

total_revenue = summary["revenue_ttc"].sum()
total_vat = summary["vat"].sum()
total_costs = summary["variable_costs"].sum() + summary["fixed_costs"].sum() + summary["driver_bonus"].sum()
total_profit = summary["net_profit"].sum()
margin = (total_profit / summary["revenue_ht"].sum() * 100) if summary["revenue_ht"].sum() else 0

cols = st.columns(5)
with cols[0]:
    render_metric("CA TTC", compact_mad(total_revenue))
with cols[1]:
    render_metric("TVA", compact_mad(total_vat))
with cols[2]:
    render_metric("Charges totales", compact_mad(total_costs))
with cols[3]:
    render_metric("Resultat net", compact_mad(total_profit), pct(margin))
with cols[4]:
    render_metric("Livraisons", f"{int(summary['deliveries'].sum())}")

tabs = st.tabs(["Vue generale", "Vehicules", "Tournees", "Charges", "Saisie"])

with tabs[0]:
    left, right = st.columns([1.45, 1])

    with left:
        st.subheader("Resultat net par vehicule")
        profit_chart = (
            alt.Chart(summary)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("vehicle_id:N", title="Vehicule", sort="-y"),
                y=alt.Y("net_profit:Q", title="Resultat net"),
                color=alt.condition(
                    alt.datum.net_profit >= 0,
                    alt.value("#2f7d57"),
                    alt.value("#b42318"),
                ),
                tooltip=[
                    "vehicle_id",
                    "driver",
                    alt.Tooltip("deliveries:Q", title="Livraisons", format=",.0f"),
                    alt.Tooltip("revenue_ttc:Q", title="CA TTC MAD", format=",.0f"),
                    alt.Tooltip("net_profit:Q", title="Resultat net MAD", format=",.0f"),
                    alt.Tooltip("margin:Q", title="Marge", format=".1f"),
                ],
            )
            .properties(height=330)
        )
        st.altair_chart(profit_chart, use_container_width=True)

    with right:
        st.subheader("Structure des charges")
        costs = pd.DataFrame(
            [
                {"category": "Carburant", "amount": summary["fuel"].sum()},
                {"category": "Peages", "amount": summary["tolls"].sum()},
                {"category": "Autres frais", "amount": summary["other_costs"].sum()},
                {"category": "Charges fixes", "amount": summary["fixed_costs"].sum()},
                {"category": "Primes", "amount": summary["driver_bonus"].sum()},
            ]
        )
        cost_chart = (
            alt.Chart(costs)
            .mark_arc(innerRadius=62)
            .encode(
                theta=alt.Theta("amount:Q"),
                color=alt.Color("category:N", title=None),
                tooltip=["category", alt.Tooltip("amount:Q", format=",.0f")],
            )
            .properties(height=330)
        )
        st.altair_chart(cost_chart, use_container_width=True)

    st.subheader("Objectifs mensuels")
    objective_chart = (
        alt.Chart(summary)
        .mark_bar(cornerRadius=4)
        .encode(
            x=alt.X("objective_progress:Q", title="Progression objectif (%)"),
            y=alt.Y("vehicle_id:N", title=None, sort="-x"),
            color=alt.condition(alt.datum.objective_progress >= 100, alt.value("#2f7d57"), alt.value("#315f9f")),
            tooltip=[
                "vehicle_id",
                alt.Tooltip("revenue_ttc:Q", title="CA TTC MAD", format=",.0f"),
                alt.Tooltip("objective:Q", title="Objectif MAD", format=",.0f"),
                alt.Tooltip("objective_progress:Q", title="Progression", format=".1f"),
            ],
        )
        .properties(height=230)
    )
    st.altair_chart(objective_chart, use_container_width=True)

with tabs[1]:
    display = summary[
        [
            "vehicle_id",
            "plate",
            "driver",
            "type",
            "status",
            "missions",
            "deliveries",
            "revenue_ttc",
            "variable_costs",
            "fixed_costs",
            "driver_bonus",
            "net_profit",
            "margin",
            "objective_progress",
        ]
    ].rename(
        columns={
            "vehicle_id": "Vehicule",
            "plate": "Plaque",
            "driver": "Chauffeur",
            "type": "Type",
            "status": "Statut",
            "missions": "Tournees",
            "deliveries": "Livraisons",
            "revenue_ttc": "CA TTC",
            "variable_costs": "Charges tournees",
            "fixed_costs": "Charges fixes",
            "driver_bonus": "Prime chauffeur",
            "net_profit": "Resultat net",
            "margin": "Marge %",
            "objective_progress": "Objectif %",
        }
    )
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "CA TTC": st.column_config.NumberColumn(format="%d MAD"),
            "Charges tournees": st.column_config.NumberColumn(format="%d MAD"),
            "Charges fixes": st.column_config.NumberColumn(format="%d MAD"),
            "Prime chauffeur": st.column_config.NumberColumn(format="%d MAD"),
            "Resultat net": st.column_config.NumberColumn(format="%d MAD"),
            "Marge %": st.column_config.NumberColumn(format="%.1f%%"),
            "Objectif %": st.column_config.ProgressColumn(min_value=0, max_value=120, format="%.0f%%"),
        },
    )

with tabs[2]:
    mission_display = missions.merge(
        database.read_vehicles()[["vehicle_id", "driver", "plate"]], on="vehicle_id", how="left"
    )
    mission_display = mission_display[
        [
            "date",
            "vehicle_id",
            "plate",
            "driver",
            "client",
            "route",
            "deliveries",
            "revenue_ttc",
            "vat",
            "variable_costs",
            "driver_bonus",
            "net_profit_before_fixed",
        ]
    ].rename(
        columns={
            "date": "Date",
            "vehicle_id": "Vehicule",
            "plate": "Plaque",
            "driver": "Chauffeur",
            "client": "Client",
            "route": "Tournee",
            "deliveries": "Livraisons",
            "revenue_ttc": "CA TTC",
            "vat": "TVA",
            "variable_costs": "Charges tournee",
            "driver_bonus": "Prime chauffeur",
            "net_profit_before_fixed": "Resultat avant charges fixes",
        }
    )
    st.dataframe(mission_display.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

with tabs[3]:
    cost_display = fixed_costs.merge(
        database.read_vehicles()[["vehicle_id", "driver", "plate"]], on="vehicle_id", how="left"
    )
    cost_display = cost_display.rename(
        columns={
            "date": "Date",
            "vehicle_id": "Vehicule",
            "plate": "Plaque",
            "driver": "Chauffeur",
            "category": "Categorie",
            "amount": "Montant",
        }
    )
    st.dataframe(cost_display.sort_values("Date", ascending=False), use_container_width=True, hide_index=True)

with tabs[4]:
    st.subheader("Ajouter une tournee")
    add_mission_form()
    st.divider()
    st.subheader("Ajouter une charge de flotte")
    add_cost_form()

st.sidebar.divider()
st.sidebar.caption("Modele Sapresss: tournees, livraisons, charges, TVA 20%, resultat et performance par vehicule.")

