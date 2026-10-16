"""Reference data from docs/decisions.md (#20 to #22, #24); options come from here."""

from dataclasses import dataclass

from core.types import Option


@dataclass(frozen=True)
class Venue:
    id: int
    city: str
    name: str
    capacity: int


CITIES = (
    "Mumbai",
    "Delhi NCR",
    "Bengaluru",
    "Hyderabad",
    "Pune",
    "Kolkata",
    "Chennai",
    "Ahmedabad",
    "Jaipur",
    "Indore",
)

VENUES = (
    Venue(1, "Mumbai", "Mahalaxmi Maidan", 30000),
    Venue(2, "Mumbai", "Bandra Waterfront", 4000),
    Venue(3, "Delhi NCR", "Dwarka Maidan", 25000),
    Venue(4, "Delhi NCR", "Aerocity Terrace", 3500),
    Venue(5, "Bengaluru", "Whitefield Commons", 20000),
    Venue(6, "Bengaluru", "Indiranagar Yard", 2000),
    Venue(7, "Hyderabad", "Gachibowli Fields", 18000),
    Venue(8, "Pune", "Baner Greens", 12000),
    Venue(9, "Pune", "Koregaon Park Lawns", 6000),
    Venue(10, "Kolkata", "Salt Lake Esplanade", 15000),
    Venue(11, "Chennai", "ECR Seafront", 12000),
    Venue(12, "Ahmedabad", "Sabarmati Riverside", 10000),
    Venue(13, "Jaipur", "Jal Mahal Terrace", 5000),
    Venue(14, "Indore", "Vijay Nagar Commons", 4000),
)

BUDGET_OPTIONS = (
    Option("lt_1500", "Under ₹1,500"),
    Option("1500_3000", "₹1,500–3,000"),
    Option("3000_6000", "₹3,000–6,000"),
    Option("gte_6000", "₹6,000+"),
)

GROUP_OPTIONS = (
    Option("1", "1"),
    Option("2", "2"),
    Option("3_5", "3–5"),
    Option("6_plus", "6+"),
)
