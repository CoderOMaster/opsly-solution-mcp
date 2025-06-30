import os
import google.generativeai as genai
from connections.neo4j_login import connect_to_neo4j

# --- CONFIGURATION ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# --- GRAPH SCHEMA FOR PROMPT CONTEXT ---
GRAPH_SCHEMA = """
Neo4j Graph Schema:
Nodes:
- Repo(name: string)
- File(path: string, module: string, repo: string)
- Function(qualified_name: string, name: string, lineno: int, file: string, repo: string, code: string)
- Class(qualified_name: string, name: string, lineno: int, file: string, repo: string, code: string)
- ExternalModule(name: string)

Relationships:
- (Repo)-[:CONTAINS]->(File)
- (File)-[:DECLARES_FUNCTION]->(Function)
- (File)-[:DECLARES_CLASS]->(Class)
- (File)-[:IMPORTS]->(File)
- (File)-[:IMPORTS]->(ExternalModule)
- (Function)-[:CALLS]->(Function)
- (Class)-[:INHERITS]->(Class)

Query Patterns for Better Matching:
1. Case-insensitive partial match: 
   MATCH (f:Function) WHERE toLower(f.name) CONTAINS toLower('forecast') RETURN f.name, f.code
   
2. Regular expression match (flexible pattern matching):
   MATCH (c:Class) WHERE c.name =~ '(?i).*forecast.*' RETURN c.name, c.code
   
3. Fuzzy search with similarity scoring (requires APOC):
   MATCH (f:Function)
   WITH f, apoc.text.distance(toLower(f.name), toLower('forcast')) as distance
   WHERE distance < 3
   RETURN f.name, f.code, distance
   ORDER BY distance
   
4. Find functions with similar functionality:
   MATCH (f:Function)
   WHERE any(prop IN ['name', 'code'] WHERE toLower(f[prop]) CONTAINS toLower('predict'))
   RETURN DISTINCT f.name, f.code
"""

# --- TOOL IMPLEMENTATION ---

def query_knowledge_graph(natural_language_query: str) -> str:
    """
    Takes a natural language query, converts it to a Cypher query using an LLM,
    executes it against the Neo4j database, and returns the result.

    Args:
        natural_language_query: The user's question in plain English.

    Returns:
        A string containing the result of the query or an error message.
    """
    print(f"[graph_tool] Received query: {natural_language_query}")

    # 1. Convert natural language to Cypher using Gemini
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Convert the user's question into a single, executable Cypher query using the following schema.
        
        IMPORTANT:
        - Prefer case-insensitive CONTAINS or regex matches over exact matches
        - For text searches, use toLower() for case-insensitive comparison
        - For partial matches, use CONTAINS or regex patterns
        - When searching for functionality, check both names and code content
        - Return only the Cypher query with no explanation
        
        Schema:
        {GRAPH_SCHEMA}
        
        User Question:
        {natural_language_query}
        
        Cypher Query (use CONTAINS, toLower(), or regex patterns for better matching):
        """
        response = model.generate_content(prompt)
        cypher_query = response.text.strip().replace('`', '')
        if not cypher_query.startswith("MATCH"):
            raise ValueError("Generated query is not a valid Cypher query.")
        print(f"[graph_tool] Generated Cypher: {cypher_query}")
    except Exception as e:
        return f"Error generating Cypher query: {e}"

    # 2. Execute the Cypher query with retry logic for APOC functions
    driver = None
    try:
        driver = connect_to_neo4j()
        with driver.session() as session:
            # First try the generated query
            try:
                result = session.run(cypher_query)
                records = [record.data() for record in result]
                if records:
                    return str(records)
            except Exception as e:
                if 'apoc' in str(e).lower() and 'not available' in str(e).lower():
                    # If APOC is not available, modify the query to use basic matching
                    cypher_query = cypher_query.replace('apoc.text.distance', '// apoc.text.distance not available, using basic matching')
                    cypher_query = cypher_query.replace('apoc.text.similarity', '// apoc.text.similarity not available, using basic matching')
                    result = session.run(cypher_query)
                    records = [record.data() for record in result]
                    if records:
                        return str(records)
                raise e
                
            # If we get here, no results were found
            suggestion = ""
            if 'CONTAINS' not in cypher_query and 'toLower' not in cypher_query and '=~' not in cypher_query:
                # If no fuzzy matching was used, suggest trying with it
                suggestion = "\n\nTry rephrasing your query to be more specific or use different keywords."
            
            return f"No results found.{suggestion}" if not records else str(records)
    except Exception as e:
        return f"Error executing Cypher query: {e}"
    finally:
        if driver:
            driver.close()
        