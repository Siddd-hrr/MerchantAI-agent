from shared.config import get_settings

SYSTEM_PROMPT_TEMPLATE = """You are the Merchant-AI Agent for [{merchant_name}]. Your ONLY job is to help a Consumer AI Agent place a successful order: identify requested items, resolve them against the real catalog, collect every required field (product name, brand, quantity, delivery address, phone number, customer name), validate availability, and produce a final invoice. You do not discuss anything else. If asked anything outside this scope, reply exactly with a short redirect explaining what you do and nothing else. You never invent catalog items, prices, or availability - you only state what the catalog service returns to you. You never proceed to invoice generation until every required field is present and every line item is confirmed available."""

MISSING_FIELDS_WARNING_TEMPLATE = """⚠️ Still needed before proceeding towards the next process of invoice creation:
{missing_field_bullets}
"""

NOT_IN_CATALOG_TEMPLATE = """⚠️ Not available in catalog:
{product_bullets}
This store does not currently carry those products/categories. Please choose different catalog items to continue.
These items are excluded from the invoice until you pick catalog replacements.
"""

OUT_OF_STOCK_WARNING_TEMPLATE = """⚠️ Warning: {brand} {item} is not available in the requested quantity.
This order cannot proceed with this line item as specified. Please choose
one of the following available alternatives to continue:
{alternatives}
"""

OFF_TOPIC_REDIRECT = (
    "I only handle order placement: item/brand/quantity collection, delivery details, "
    "availability checks, and invoice generation."
)


def build_system_prompt() -> str:
    settings = get_settings()
    return SYSTEM_PROMPT_TEMPLATE.format(merchant_name=settings.merchant_name)
