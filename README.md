# MCP-Enhanced Code Search and Documentation

This repository implements a robust Model Context Protocol (MCP) solution for the [Opsly Interview Assignment](https://github.com/Opsly/opsly-interview). It provides a streamlined interface for querying and retrieving code snippets, enhanced by an optional knowledge graph for accelerated NLP-driven Cypher queries. An LLM-based documentation generator and a clean Streamlit UI complete the feature set.

---

## 📋 Table of Contents

* [Features](#-features)
* [Tech Stack](#-tech-stack)
* [Project Structure](#-project-structure)
* [Installation](#-installation)
* [Usage](#-usage)

  * [1. Clone and Install Dependencies](#1-clone-and-install-dependencies)
  * [2. (Optional) Knowledge Graph Setup](#2-optional-knowledge-graph-setup)
  * [3. Launch the Streamlit App](#3-launch-the-streamlit-app)
* [Configuration](#-configuration)
* [Development](#-development)
* [Contributing](#-contributing)
* [License](#-license)

---

## 🚀 Features

* **MCP Server**: Handles all assignment queries via the Model Context Protocol, ensuring modular and extensible tool integration.
* **Knowledge Graph (Optional)**: Uses a graph database to embed and query repository content via Cypher, providing faster retrieval and richer NLP capabilities.
* **LLM.txt Generator**: Automatically maps, structures, and summarizes the entire repository using the Dspy library.
* **Streamlit Interface**: User-friendly front-end for interactive querying and code exploration.
* **Gemini 2 Flash**: All LLM calls are executed using Gemini 2 Flash for high-performance inference.

---

## 🛠 Tech Stack

* **Python 3.8+**
* **MCP Server**
* **sktime** (chosen for its extensive, active ML function library)
* **Dspy** (for LLM.txt generation)
* **Streamlit** (for the clean GUI)
* **Gemini 2 Flash** (LLM serving)
* **Neo4j** (or any Cypher-compatible graph DB) for knowledge graph

---

## 🗂 Project Structure

```
├── app.py                 # Streamlit UI entry point
├── mcp_server.py          # MCP server implementation
├── repo_cloner.py         # Normalizes and cleans the repo for graph ingestion
├── knowledge.py           # Embeds repo content into the knowledge graph
├── llm_txt_generator.py   # Generates repository structure & summary with Dspy
├── requirements.txt       # Python dependencies
└── README.md              # Project documentation
```

---

## ⚙️ Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/yourusername/opsly-mcp-sktime.git
   cd opsly-mcp-sktime
   ```
2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

---

## 🏃‍♂️ Usage

### 1. Clone and Install Dependencies

Follow the [Installation](#-installation) steps above.

### 2. (Optional) Knowledge Graph Setup

> **Note:** Skip these steps if you only want the MCP functionality without the knowledge graph.

1. **Start your graph database** (e.g., Neo4j)
2. **Run the repo cloner** to normalize files:

   ```bash
   python3 repo_cloner.py
   ```
3. **Embed into the graph**:

   ```bash
   python3 knowledge.py
   ```

### 3. Launch the Streamlit App

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501` to interact with the MCP server via the GUI.

---

## 🔧 Configuration

Adjust settings in `config.py` (create one from `config.example.py`) to specify:

* MCP server host/port
* Graph database connection URI, username, and password
* LLM model endpoints (e.g., Gemini 2 Flash)

---

