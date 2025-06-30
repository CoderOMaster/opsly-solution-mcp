import streamlit as st
import asyncio
import os
import json
import time
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv
from graph_tool import query_knowledge_graph
from dspy_files.main import generate_llms_txt_for_dspy

# --- Helper Functions & Setup ---

def run_async(coro):
    """Helper to run async code in a way that works with Streamlit."""
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "Event loop is closed" in str(e):
            # If the event loop is closed, create a new one and try again
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        else:
            raise

def clean_schema(schema):
    """Recursively rebuilds a schema, excluding unsupported keys."""
    if not isinstance(schema, dict):
        return schema
    cleaned = {}
    for key, value in schema.items():
        if key in ["additionalProperties", "$schema"]:
            continue
        if isinstance(value, dict):
            cleaned[key] = clean_schema(value)
        elif isinstance(value, list):
            cleaned[key] = [clean_schema(item) for item in value]
        else:
            cleaned[key] = value
    return cleaned

@st.cache_resource
def get_mcp_tools():
    """
    Connects to the MCP server and retrieves the list of available tools.
    Caches the result to avoid reconnecting on every Streamlit rerun.
    """
    server_params = StdioServerParameters(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")},
    )

    async def fetch_tools():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                mcp_tools_list = await session.list_tools()
                gemini_tools = []
                for tool in mcp_tools_list.tools:
                    schema_as_dict = json.loads(json.dumps(tool.inputSchema))
                    cleaned_input_schema = clean_schema(schema_as_dict)
                    function_decl = {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": cleaned_input_schema,
                    }
                    gemini_tools.append(types.Tool(function_declarations=[function_decl]))
                return gemini_tools

    return asyncio.run(fetch_tools())



async def call_mcp_tool(function_call):
    """Establishes a new MCP session to call a single tool."""
    try:
        server_params = StdioServerParameters(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")},
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                try:
                    await session.initialize()
                    result = await session.call_tool(
                        function_call.name, 
                        arguments=dict(function_call.args)
                    )
                    
                    if not result.content:
                        raise ValueError("No content in response from MCP server")
                        
                    try:
                        content = json.loads(result.content[0].text)
                    except (json.JSONDecodeError, IndexError, AttributeError):
                        content = result.content[0].text if result.content else "No content returned from tool."
                    
                    # Add a small delay to allow the subprocess transport to clean up
                    # before the event loop is closed by asyncio.run().
                    await asyncio.sleep(0.1)

                    return types.Part(
                        function_response=types.FunctionResponse(
                            name=function_call.name,
                            response={"content": content},
                        )
                    )
                    
                except Exception as e:
                    error_msg = f"Error calling tool '{function_call.name}': {str(e)}"
                    st.error(error_msg)
                    await asyncio.sleep(0.1) # Also sleep on error
                    return types.Part(
                        function_response=types.FunctionResponse(
                            name=function_call.name,
                            response={"content": error_msg},
                        )
                    )
                
    except Exception as e:
        error_msg = f"Failed to establish MCP session: {str(e)}"
        st.error(error_msg)
        return types.Part(
            function_response=types.FunctionResponse(
                name=function_call.name if 'function_call' in locals() else "unknown",
                response={"content": error_msg},
            )
        )

# --- Streamlit App ---

# Load environment variables
load_dotenv()

# Configure the Gemini client
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    st.error("GEMINI_API_KEY environment variable is not set. Please set it in your .env file.")
    st.stop()

# Use the Client API, which is compatible with the user's environment
client = genai.Client(api_key=api_key)

# No longer need a global loop

st.title("GitHub Repository Assistant")
st.caption("An assistant to help you analyze and work with GitHub repositories.")


# --- Knowledge Graph Query UI ---
with st.expander("Query the Code Knowledge Graph"):
    graph_query = st.text_input("Ask a question about the code's structure:", key="graph_query_input")
    if st.button("Query Graph", key="graph_query_button"):
        if graph_query:
            with st.spinner("Querying the knowledge graph..."):
                try:
                    result = query_knowledge_graph(graph_query)
                    st.markdown("##### Graph Query Result")
                    # The result is a stringified list of dicts, so we can load it back
                    try:
                        st.json(json.loads(result))
                    except (json.JSONDecodeError, TypeError):
                        st.code(result, language='text')
                except Exception as e:
                    st.error(f"An error occurred while querying the graph: {e}")
        else:
            st.warning("Please enter a query.")

# --- Repository Summarization ---
with st.expander("📝 Repository Summarization", expanded=False):
    st.subheader("Generate Repository Summary")
    
    # Add a text input for the repository URL
    repo_url = st.text_input(
        "GitHub Repository URL",
        value="https://github.com/sktime/sktime",
        key="repo_url_input"
    )
    
    # Add a button to trigger the summarization
    if st.button("Generate Summary", key="summarize_btn"):
        if not repo_url:
            st.warning("Please enter a GitHub repository URL")
        else:
            with st.spinner("Analyzing repository and generating summary..."):
                try:
                    # Store the result in session state
                    if 'summary_result' not in st.session_state:
                        st.session_state.summary_result = None
                    
                    # Call the summarization function with the provided URL
                    st.session_state.summary_result = generate_llms_txt_for_dspy(repo_url)
                    
                except Exception as e:
                    st.error(f"An error occurred while generating the summary: {str(e)}")
    
    # Display the result if available
    if 'summary_result' in st.session_state and st.session_state.summary_result is not None:
        st.subheader("Generated Summary")
        st.download_button(
            label="Download llms.txt",
            data=st.session_state.summary_result.llms_txt_content,
            file_name="llms.txt",
            mime="text/plain"
        )
        st.code(st.session_state.summary_result.llms_txt_content, language="text")

# --- Main Chat Interface ---
st.subheader("General Chat Assistant")


# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant", 
            "content": "👋 Hi! I'm your GitHub repository assistant."
        }
    ]

# Get the tools (cached)
try:
    gemini_tools = get_mcp_tools()
except Exception as e:
    st.error(f"Failed to load MCP tools: {e}")
    st.stop()

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# React to user input
if prompt := st.chat_input("What would you like to know about the repository?"):
    # Add repository context to the prompt
    enhanced_prompt = f"{prompt} (Focus on the repository: sktime/sktime library strictly)"

    st.chat_message("user").markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": enhanced_prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                # Convert UI history to the format expected by the Gemini API
                api_history = []
                for msg in st.session_state.messages:
                    if msg["role"] == "assistant":
                        role = "model"
                        parts = [{"text": msg["content"]}]
                    elif msg["role"] == "function":
                        role = "function"
                        parts = [{"function_response": msg["content"]}]
                    else:
                        role = "user"
                        parts = [{"text": msg["content"]}]
                    
                    api_history.append({"role": role, "parts": parts})

                generation_config = types.GenerateContentConfig(tools=gemini_tools)

                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=api_history,  # Pass the full conversation history
                    config=generation_config,
                )

                if not response.candidates or not response.candidates[0].content.parts:
                    response_text = response.text or "I'm sorry, I couldn't generate a response."
                else:
                    part = response.candidates[0].content.parts[0]
                    if part.function_call:
                        function_call = part.function_call
                        st.info(f"Calling tool: `{function_call.name}` with args: `{dict(function_call.args)}`")
                        
                        api_history.append({"role": "model", "parts": [part]})

                        # Create a new event loop for the async call
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            # Add the model's tool call request to the history as a dict
                            api_history.append({
                                "role": "model",
                                "parts": [{
                                    "function_call": {
                                        "name": function_call.name,
                                        "args": dict(function_call.args)
                                    }
                                }]
                            })

                            st.info(f"Calling MCP tool: `{function_call.name}`")
                            # Use our helper to run the async code
                            tool_response_part = run_async(call_mcp_tool(function_call))

                            # Add the function response to history
                            api_history.append({
                                "role": "function",
                                "parts": [{
                                    "function_response": {
                                        "name": function_call.name,
                                        "response": tool_response_part.function_response.response
                                    }
                                }]
                            })
                        except Exception as e:
                            error_msg = f"Error executing tool: {str(e)}"
                            st.error(error_msg)
                            api_history.append({
                                "role": "function",
                                "parts": [{
                                    "function_response": {
                                        "name": function_call.name,
                                        "response": {"content": error_msg}
                                    }
                                }]
                            })
                        finally:
                            loop.close()

                        final_response = client.models.generate_content(
                            model="gemini-2.0-flash",
                            contents=api_history,
                            config=generation_config,
                        )
                        response_text = final_response.text
                    else:
                        response_text = response.text

                st.markdown(response_text)
                st.session_state.messages.append({"role": "assistant", "content": response_text})

            except Exception as e:
                st.error(f"An error occurred: {e}")
                st.session_state.messages.append({"role": "assistant", "content": f"Error: {e}"})
