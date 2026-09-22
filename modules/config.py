from __future__ import annotations

from dataclasses import dataclass

PROFICIENCY = {
    "Awareness": 1,
    "Working": 2,
    "Proficient": 3,
    "Expert": 4,
}
PROFICIENCY_LABELS = list(PROFICIENCY.keys())

# PSA working week used to translate between the source capacity percentage
# and the hours resource managers allocate across projects.
STANDARD_WEEK_HOURS = 42.5

# Governed HR grade codes. Analyst and Associate Consultant share grade 130;
# designation remains the user-facing distinction between those two roles.
GRADE_LABELS = {
    130: "Analyst / Associate Consultant",
    140: "Consultant",
    150: "Senior Consultant",
    160: "Engagement Manager",
    170: "Principal",
    180: "Senior Principal",
}
GRADE_CODES = list(GRADE_LABELS)
DESIGNATION_TO_GRADE = {
    "Analyst": 130,
    "Associate Consultant": 130,
    "Consultant": 140,
    "Senior Consultant": 150,
    "Engagement Manager": 160,
    "Principal": 170,
    "Senior Principal": 180,
}
DESIGNATIONS = list(DESIGNATION_TO_GRADE)
# Compatibility alias for integrations that import the old symbol.
GRADE_LEVELS = DESIGNATIONS

LANGUAGES = [
    "English", "Hindi", "French", "Spanish", "German", "Mandarin", "Japanese",
    "Portuguese", "Italian", "Arabic", "Korean", "Dutch", "Russian",
]

# Resource work country remains a country-level master-data attribute.
# It is intentionally NOT used as the normal staffing-request location filter.
LOCATIONS = [
    "India", "UK", "France", "Germany", "Spain", "USA", "Canada",
    "Singapore", "Japan", "Australia", "Philippines",
]

# Exact IANA time zones governed by the current staffing-sheet taxonomy.
# Resource records are validated against this governed set.
TIME_ZONES = [
    "America/Chicago", "America/Los_Angeles", "America/New_York",
    "America/Toronto", "Asia/Kolkata", "Asia/Manila", "Asia/Singapore",
    "Asia/Tokyo", "Australia/Sydney", "Europe/Berlin", "Europe/London",
    "Europe/Paris",
]

# Legacy country-level mapping retained for compatibility with older callers.
# New staffing logic must use exact resource.time_zone values instead.
LOCATION_TO_TIMEZONE = {
    "India": "Asia/Kolkata",
    "UK": "Europe/London",
    "France": "Europe/Paris",
    "Germany": "Europe/Berlin",
    "Spain": "Europe/Paris",
    "USA": "America/New_York",
    "Canada": "America/Toronto",
    "Singapore": "Asia/Singapore",
    "Japan": "Asia/Tokyo",
    "Australia": "Australia/Sydney",
    "Philippines": "Asia/Manila",
}

# Client locations are governed at city level because client working hours
# and travel requirements are tied to the actual client location.
CLIENT_LOCATIONS = [
    "Australia - Sydney",
    "Canada - Toronto",
    "France - Paris",
    "Germany - Berlin",
    "Germany - Frankfurt",
    "India",
    "India - Hyderabad",
    "Japan - Tokyo",
    "Philippines - Manila",
    "Singapore",
    "Spain - Madrid",
    "UK - London",
    "USA - Chicago",
    "USA - Los Angeles",
    "USA - New York",
    "USA - San Francisco",
]

CLIENT_LOCATION_TO_COUNTRY = {
    "Australia - Sydney": "Australia",
    "Canada - Toronto": "Canada",
    "France - Paris": "France",
    "Germany - Berlin": "Germany",
    "Germany - Frankfurt": "Germany",
    "India": "India",
    "India - Hyderabad": "India",
    "Japan - Tokyo": "Japan",
    "Philippines - Manila": "Philippines",
    "Singapore": "Singapore",
    "Spain - Madrid": "Spain",
    "UK - London": "UK",
    "USA - Chicago": "USA",
    "USA - Los Angeles": "USA",
    "USA - New York": "USA",
    "USA - San Francisco": "USA",
}

# Canonical IANA timezone for each governed client city/location.
# This is deliberately separate from resource work-country data.
CLIENT_LOCATION_TO_TIMEZONE = {
    "Australia - Sydney": "Australia/Sydney",
    "Canada - Toronto": "America/Toronto",
    "France - Paris": "Europe/Paris",
    "Germany - Berlin": "Europe/Berlin",
    "Germany - Frankfurt": "Europe/Berlin",
    "India": "Asia/Kolkata",
    "India - Hyderabad": "Asia/Kolkata",
    "Japan - Tokyo": "Asia/Tokyo",
    "Philippines - Manila": "Asia/Manila",
    "Singapore": "Asia/Singapore",
    "Spain - Madrid": "Europe/Berlin",
    "UK - London": "Europe/London",
    "USA - Chicago": "America/Chicago",
    "USA - Los Angeles": "America/Los_Angeles",
    "USA - New York": "America/New_York",
    "USA - San Francisco": "America/Los_Angeles",
}

# Geography expertise is a capability, not physical work location. These
# values are taken from the current resources.csv geography_expertise field.
GEOGRAPHIES = [
    "ANZ", "APAC", "Australia", "Canada", "DACH", "East Asia",
    "Europe", "France", "Germany", "India", "Italy", "Japan",
    "North America", "Philippines", "Singapore", "South Asia",
    "Southeast Asia", "Southern Europe", "Spain", "UK", "USA",
    "United States", "Western Europe",
]


def country_from_client_location(client_location: str) -> str | None:
    """Return the governed client country without fuzzy inference."""
    value = str(client_location or "").strip()
    return CLIENT_LOCATION_TO_COUNTRY.get(value)

DOMAINS = [
    "Healthcare", "Life Sciences", "Commercial Analytics", "Patient Services",
    "Market Analytics", "Real World Evidence", "Clinical Analytics",
    "Pharmacovigilance", "Manufacturing Analytics", "Insurance", "Technology",
    "Public Sector", "Financial Services", "Pricing & Promotion",
]

THERAPEUTIC_AREAS = [
    "Oncology", "Immunology", "Cardiology", "Diabetes", "Obesity", "Neurology",
    "Rare Disease", "Respiratory", "Dermatology", "Vaccines", "Hematology",
    "Ophthalmology", "Women's Health", "Patient Services", "Cross-therapy",
]

KPI_FOCUS_AREAS = [
    "Adherence", "Persistence", "Abandonment", "Refill Rate", "Patient Starts",
    "Patient Reach", "Time to Diagnosis", "Drop-off Rate", "Copay Utilisation",
    "Enrolment Rate", "Conversion", "Market Share", "NBRx", "TRx", "Market Growth",
    "HCP Reach", "HCP Engagement", "Channel Conversion", "Forecast Accuracy",
    "Service Level", "Case Resolution", "Call Abandonment", "Average Handling Time",
    "First Call Resolution", "Incremental Sales",
]

TRAVEL_REQUIREMENTS = [
    "No", "Yes",
]

SKILL_CATALOG = [
    "SQL", "Python", "R", "SAS", "Excel", "Power BI", "Tableau", "Alteryx",
    "Databricks", "Snowflake", "Azure", "AWS", "GCP", "Spark", "dbt",
    "Machine Learning", "Deep Learning", "NLP", "GenAI", "Agentic AI", "MLOps",
    "Prompt Engineering", "LLM Evaluation", "RAG", "AI Governance", "Forecasting",
    "Predictive Modeling", "Clustering", "Causal Inference", "A/B Testing",
    "Data Visualization", "Data Engineering", "ETL", "Statistical Modeling",
    "Healthcare Data", "Claims Data", "EHR Data", "Clinical Trial Data",
    "Real World Evidence", "Patient Journey Analytics", "Commercial Analytics",
    "Market Access", "HEOR", "Pharmacovigilance", "Omnichannel Analytics",
    "Customer Analytics", "Supply Chain Analytics", "Financial Analytics", "Project Management",
    "Price Elasticity", "Market Mix Modeling", "Pricing Strategy", "Segmentation", "Promo Optimization",
]

SKILL_ALIASES = {
    "structured query language": "SQL",
    "powerbi": "Power BI",
    "power bi": "Power BI",
    "gen ai": "GenAI",
    "generative ai": "GenAI",
    "generative artificial intelligence": "GenAI",
    "agentic artificial intelligence": "Agentic AI",
    "agent ai": "Agentic AI",
    "large language models": "GenAI",
    "llms": "GenAI",
    "real-world evidence": "Real World Evidence",
    "rwe": "Real World Evidence",
    "healthcare analytics": "Healthcare Data",
    "clinical data": "Clinical Trial Data",
    "market mix modelling": "Market Mix Modeling",
    "mme": "Market Mix Modeling",
    "price elasticity modelling": "Price Elasticity",
    "price elasticity modeling": "Price Elasticity",
}

SEARCH_ALIASES = {
    "mmx": {"tags": {"MMX", "Market Mix Modeling"}, "skills": {"Market Mix Modeling"}},
    "pricing": {"tags": {"Pricing", "Pricing Strategy", "Price Elasticity"}, "skills": {"Price Elasticity", "Pricing Strategy"}},
    "europe": {"geographies": {"Europe"}},
    "india": {"locations": {"India"}},
    "asia": {"geographies": {"Asia", "APAC"}},
    "apac": {"geographies": {"APAC"}},
    "north america": {"geographies": {"North America"}},
}

DEFAULT_WEIGHTS = {
    "mandatory_skills": 0.35,
    "preferred_skills": 0.25,
    "proficiency": 0.20,
    "capacity": 0.20,
}

RULE_VERSION = "RM-RULES-4.1"
TAXONOMY_VERSION = "SKILL-CATALOG-2.0"
DATA_VERSION = "SYNTHETIC-2026-09.4"

@dataclass(frozen=True)
class CapacityPolicy:
    require_full_allocation: bool = True

CAPACITY_POLICY = CapacityPolicy()
