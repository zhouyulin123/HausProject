# AI Agents Configuration (LangGraph Architecture)

This document defines the configuration, roles, and interactions of the various Agents used in the AI Home Decor application. We are using a multi-agent architecture orchestrated by LangGraph.

## 1. Orchestrator Agent (Master Graph)
*   **Role:** The central router and state manager. It receives the initial user input (image + text) and determines the execution flow, passing state between specialized agents.
*   **Framework:** LangGraph `StateGraph`
*   **State Definition:**
    *   `user_input_text`: string
    *   `uploaded_image_urls`: list[string]
    *   `parsed_requirements`: dict (JSON)
    *   `image_analysis_result`: dict
    *   `generated_images`: list[string]
    *   `quote_result`: dict
    *   `current_step`: string

## 2. Requirement Parsing Agent (需求理解 Agent)
*   **Role:** Extracts structured data (JSON) from the user's natural language input.
*   **Model Recommendation:** DeepSeek-Coder / GPT-4o (Strong structured output capabilities required).
*   **Prompt Strategy:** Few-shot prompting + Strict JSON Schema output format.
*   **Input:** `user_input_text`
*   **Output:** `parsed_requirements` (JSON matching `9.2` in the project plan)
*   **Tools/Functions:** None (Relies on LLM structured output capabilities).

## 3. Image Analysis Agent (图像分析 Agent)
*   **Role:** Analyzes the uploaded room photo or floor plan to understand space type, existing layout, and potential constraints.
*   **Model Recommendation:** GPT-4o / Qwen-VL (Vision Language Models).
*   **Prompt Strategy:** Ask specific questions about the image (e.g., "What type of room is this?", "Are there any existing windows or doors?").
*   **Input:** `uploaded_image_urls`
*   **Output:** `image_analysis_result` (Structured tags and descriptions).

## 4. Drawing Dispatch Agent (绘图调度 Agent)
*   **Role:** Takes the parsed requirements and image analysis to formulate the optimal prompt and parameters for the external image generation API (e.g., ControlNet).
*   **Model Recommendation:** A fast, cheap LLM (e.g., GPT-4o-mini or DeepSeek-Chat) to act as a prompt translator.
*   **Input:** `parsed_requirements`, `uploaded_image_urls`
*   **Output:** Generates Prompts and calls external Image Generation API (via Tool/ToolNode in LangGraph).
*   **Tools:**
    *   `generate_interior_design`: An API wrapper calling SD/ControlNet or third-party interior design APIs.

## 5. Quote Calculation Agent (报价生成 Agent)
*   **Role:** Calculates the estimated price range based on the structured requirements and predefined pricing rules.
*   **Implementation:** This might not need a complex LLM; it can be a deterministic Python function (a standard node in LangGraph) that executes the pricing logic based on database rules.
*   **Input:** `parsed_requirements`
*   **Output:** `quote_result` (Price ranges and breakdowns).

## LangGraph Workflow Example

```python
# Conceptual Workflow
from langgraph.graph import StateGraph

workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("parse_requirements", requirement_parsing_agent)
workflow.add_node("analyze_image", image_analysis_agent)
workflow.add_node("calculate_quote", quote_calculation_agent)
# workflow.add_node("generate_image", drawing_dispatch_agent) # Might be asynchronous or separate

# Define Edges
workflow.set_entry_point("parse_requirements")
# Parallel processing if possible
workflow.add_edge("parse_requirements", "calculate_quote")
# ...
```