"""Re-send an ATS resume to the review bot (after caption fix)."""

import asyncio
import sys

from app.telegram.service import telegram_service


async def main() -> None:
    ats_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    ok = await telegram_service.notify_linkedin_ats_resume(ats_id)
    print(f"ats_id={ats_id} sent={ok}")


if __name__ == "__main__":
    asyncio.run(main())
