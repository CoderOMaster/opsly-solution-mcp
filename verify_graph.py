from connections.neo4j_login import connect_to_neo4j

def check_code_snippets():
    """
    Connects to Neo4j and checks if code snippets exist on Function or Class nodes.
    """
    driver = None
    try:
        driver = connect_to_neo4j()
        query = """
        MATCH (n)
        WHERE (n:Function OR n:Class) AND n.code IS NOT NULL
        RETURN n.qualified_name AS name, n.code AS code_snippet
        LIMIT 5
        """
        with driver.session() as session:
            results = session.run(query)
            records = list(results)
            if not records:
                print("No code snippets found in the graph for Function or Class nodes.")
                return

            print("Found code snippets. Here are a few examples:\n")
            for i, record in enumerate(records):
                print(f"--- {i+1}. {record['name']} ---\n")
                print(record['code_snippet'])
                print("\n" + "="*40 + "\n")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if driver:
            driver.close()
            print("Connection closed.")

if __name__ == "__main__":
    check_code_snippets()
