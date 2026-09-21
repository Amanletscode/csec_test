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

LOCATIONS = [
    "India", "UK", "France", "Germany", "Spain", "USA", "Canada",
    "Singapore", "Japan", "Australia", "Philippines",
]

TIME_ZONES = [
    "Asia/Kolkata", "Europe/London", "Europe/Paris", "Europe/Berlin",
    "America/New_York", "America/Chicago", "America/Los_Angeles",
    "America/Toronto", "Asia/Singapore", "Asia/Manila", "Asia/Tokyo", "Australia/Sydney",
]

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
