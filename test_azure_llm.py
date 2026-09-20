import os

from modules.llm_adapter import AzureLLMAdapter


def main():

    adapter = AzureLLMAdapter()

    print("=" * 60)
    print("Azure OpenAI connectivity test")
    print("=" * 60)

    print("Configured:", adapter.configured)

    if not adapter.configured:
        print()
        print("Azure OpenAI is NOT configured.")
        print()
        print("Required environment variables:")
        print("AZURE_OPENAI_ENDPOINT")
        print("AZURE_OPENAI_API_KEY")
        print("AZURE_OPENAI_DEPLOYMENT")
        return

    schema = {
        "intent": [
            "expert_finder",
            "capability_discovery",
            "resource_matching",
        ],
        "skills": [
            "SQL",
            "Python",
            "GenAI",
            "Data Engineering",
            "Price Elasticity",
        ],
        "domains": [
            "Healthcare",
            "Commercial Analytics",
            "Technology",
        ],
        "locations": [
            "India",
            "Germany",
            "USA",
            "UK",
        ],
        "geographies": "list[str]",
        "time_zones": [
            "Asia/Kolkata",
            "Europe/Berlin",
            "America/New_York",
        ],
        "languages": [
            "English",
            "Hindi",
            "German",
        ],
        "designations": [
            "Analyst",
            "Associate Consultant",
            "Consultant",
            "Senior Consultant",
            "Engagement Manager",
            "Principal",
            "Senior Principal",
        ],
        "availability_min": "number 0..100 or null",
        "availability_max": "number 0..100 or null",
        "start_date": "YYYY-MM-DD or null",
        "terms": "list[str]",
    }

    query = (
        "I need a Consultant in India who knows "
        "SQL and Python and has around 20 hours "
        "available."
    )

    print()
    print("Test query:")
    print(query)
    print()

    try:
        result = adapter.interpret(
            query,
            schema,
        )

        print("Azure OpenAI response:")
        print(result)

        print()
        print("STATUS: SUCCESS")

    except Exception as exc:
        print()
        print("STATUS: FAILED")
        print(type(exc).__name__)
        print(str(exc))


if __name__ == "__main__":
    main()