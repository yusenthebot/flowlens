#!/usr/bin/env python3
"""
FlowLens Quickstart — Simplest possible example showing core functionality.

Run with:
    python examples/quickstart.py

This minimal example demonstrates:
1. Initializing FlowLens
2. Decorating an agent function
3. Running the agent
4. Viewing the trace output
"""

import asyncio
from flowlens import FlowLens, trace_agent, trace_tool


# Step 1: Initialize FlowLens
# This creates a global tracer that decorators will use.
lens = FlowLens(
    service_name="quickstart-agent",
    export_to="console",      # Print traces to stdout
    verbose=True,             # Show import details
)


# Step 2: Decorate an agent function
# The @trace_agent decorator automatically:
# - Creates a trace
# - Records execution time
# - Captures any errors
# - Exports when done
@trace_agent(name="simple_agent")
async def my_agent(task: str) -> str:
    """A simple agent that processes a task and returns a result."""
    result = await my_tool(task)
    return f"Processed: {result}"


# Step 3: Decorate a tool function
# The @trace_tool decorator automatically:
# - Records tool invocation
# - Captures input parameters
# - Captures output summary
@trace_tool(name="process_task")
async def my_tool(input_text: str) -> str:
    """A simple tool that transforms input."""
    await asyncio.sleep(0.1)  # Simulate some work
    return input_text.upper()


# Step 4: Run the agent and see the trace
async def main():
    print("Starting FlowLens quickstart demo...\n")

    # Call the decorated agent function
    result = await my_agent("hello world")

    print(f"\nAgent result: {result}")
    print("\n✅ Check the console output above to see the trace!")


if __name__ == "__main__":
    # Run the async agent
    asyncio.run(main())

    # Clean up resources
    lens.shutdown()
