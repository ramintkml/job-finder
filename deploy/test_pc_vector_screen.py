"""Test PC chroma screening via VPS queue for the Multi-Agent project."""

from __future__ import annotations

import asyncio
import json
import urllib.request

TEXT = """Python Multi-Agent Workflow Automation
fixed: $ 250-750 USD
United States-Coraopolis
payment verified

1.Agent Design Refinement
Refine your initial concept by specifying how your agent will reason, what memory it will require, and which tools it may need to complete its tasks effectively.

2. RAG and Retrieval Design Integration
Decide whether your agent requires external knowledge or retrieval. You will define how retrieval, data grounding, and memory design will support more reliable outputs.

3. Tree-of-Thought Integration Plan
Identify where structured reasoning can improve your agent. You will define how branching, evaluation, and selection could strengthen performance on more complex tasks.

4: Multi-Agent Architecture and Coordination Plan
Extend your design into a multi-agent workflow. You will define specialized agent roles, communication patterns, and coordination logic to support more complex problem-solving.

5: Safety Guardrails and Human Intervention Plan
Specify how your system will be evaluated and monitored. You will define guardrails, logging needs, success criteria, and when human intervention should be used to improve safety and reliability.

6: Final
Combine all the above to larger project

By the end of the program, you will have built an agentic AI system from the three options provided that demonstrates your ability to design, implement, evaluate, and communicate an end-to-end solution.

Python Technical Writing Software Architecture Data Integration LangChain AI Development AI Agents Model Context Protocol MCP Agentic AI
"""


async def main() -> None:
    from app.rag.matcher import vector_screen_project, vector_screen_project_async
    from app.rag.store import backend_name

    lean = vector_screen_project(TEXT)
    print("local", backend_name(), lean.action, lean.confidence, lean.skip_reason or lean.review_reason)
    remote = await vector_screen_project_async(TEXT)
    print("async", remote.action, remote.confidence, remote.skip_reason or remote.review_reason)


if __name__ == "__main__":
    asyncio.run(main())
