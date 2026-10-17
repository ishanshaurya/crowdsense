"""Vega-Lite specs for the dashboard charts: thin lines, light grid, few ticks. Data only (Q-17)."""

from typing import Any

TEAL = "#0E6B66"
INK = "#0F2A2B"
GOLD = "#F3A712"
PRICE_COLOURS = ["#CFE2DF", "#8FBFB8", "#4C9A93", TEAL, "#0A4A47"]
CITY_COLOURS = [TEAL, GOLD, "#4C9A93", "#0A4A47", "#8FBFB8", "#52686A"]
CONFIG = {
    "view": {"stroke": None},
    "font": "Hanken Grotesk",
    "axis": {
        "grid": True,
        "gridColor": "#E4E9E5",
        "domain": False,
        "ticks": False,
        "labelColor": "#52686A",
        "labelFontSize": 12,
        "labelPadding": 6,
    },
    "legend": {"labelColor": "#52686A", "labelFontSize": 12, "symbolSize": 80},
}
WEEK_AXIS = {
    "labelAngle": 0,
    "title": None,
    "grid": False,
    "labelOverlap": True,
    "labelLimit": 220,
}

Spec = dict[str, Any]


def trend_spec() -> Spec:
    return {
        "height": 160,
        "config": CONFIG,
        "layer": [
            {"mark": {"type": "area", "color": TEAL, "opacity": 0.1, "line": False}},
            {"mark": {"type": "line", "color": TEAL, "strokeWidth": 2.5}},
        ],
        "encoding": {
            "x": {"field": "Week", "type": "ordinal", "axis": WEEK_AXIS},
            "y": {"field": "Fans", "type": "quantitative", "axis": {"title": None, "tickCount": 3}},
        },
    }


def donut_spec(labels: list[str]) -> Spec:
    return {
        "height": 150,
        "config": CONFIG,
        "mark": {"type": "arc", "innerRadius": 46, "outerRadius": 66},
        "encoding": {
            "theta": {"field": "Fans", "type": "quantitative"},
            "color": {
                "field": "Band",
                "type": "nominal",
                "sort": labels,
                "scale": {"domain": labels, "range": PRICE_COLOURS},
                "legend": {"orient": "right", "title": None},
            },
        },
    }


def growth_spec() -> Spec:
    return {
        "height": 170,
        "config": CONFIG,
        "mark": {"type": "line", "strokeWidth": 2.5},
        "encoding": {
            "x": {"field": "Week", "type": "ordinal", "axis": WEEK_AXIS},
            "y": {"field": "Fans", "type": "quantitative", "axis": {"title": None, "tickCount": 4}},
            "color": {
                "field": "City",
                "type": "nominal",
                "scale": {"range": CITY_COLOURS},
                "legend": {"orient": "bottom", "title": None, "columns": 5},
            },
        },
    }


def budget_spec(cities: list[str], bands: list[str]) -> Spec:
    """Fans per ticket price band, one stacked bar per city, biggest city first."""
    return {
        "height": {"step": 30},
        "config": CONFIG,
        "mark": {"type": "bar", "height": 18},
        "encoding": {
            "y": {
                "field": "City",
                "type": "nominal",
                "sort": cities,
                "axis": {"title": None, "grid": False, "labelFontSize": 13, "labelColor": INK},
            },
            "x": {
                "field": "Fans",
                "type": "quantitative",
                "axis": {"title": None, "tickCount": 4, "format": ","},
            },
            "color": {
                "field": "Band",
                "type": "nominal",
                "sort": bands,
                "scale": {"domain": bands, "range": PRICE_COLOURS},
                "legend": {"orient": "top", "title": None},
            },
        },
    }
