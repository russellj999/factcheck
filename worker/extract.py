import os
import asyncpg

# TODO: Replace with actual LLM call
def run_extract(text: str):
    claims = [
        {
            "claim_text": "The Earth is warming faster than expected.",
            "claim_type": "factual",
            "confidence": 0.92,
        },
        {
            "claim_text": "Apple will release a new iPhone next year.",
            "claim_type": "prediction",
            "confidence": 0.75,
        }
    ]
    import asyncio
    asyncio.run(save_claims_to_db(claims))
    return claims

async def save_claims_to_db(claims):
    conn = await asyncpg.connect(os.getenv("DATABASE_URL"))
    for c in claims:
        await conn.execute(
            """
            INSERT INTO claims (claim_text, claim_type, confidence)
            VALUES ($1, $2, $3)
            """,
            c["claim_text"], c["claim_type"], c["confidence"]
        )
    await conn.close()
