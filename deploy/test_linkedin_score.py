"""Compare lean vs PC-chroma LinkedIn relevance score."""

import asyncio

from app.linkedin.relevance import score_text_relevance, score_text_relevance_async

TEXT = """A Career with Point72's Technology Team
Develop and maintain scalable AI/ML architectures and systems.
Collaborate with data scientists, engineers, product teams to integrate AI/ML solutions.
Bachelor's or Master's degree in Computer Science. 3-7 years of experience in AI/ML engineering.
Python deep learning LLMs machine learning.
"""


async def main() -> None:
    print("lean", score_text_relevance(TEXT))
    print("async", await score_text_relevance_async(TEXT))


if __name__ == "__main__":
    asyncio.run(main())
