# Gemini CLI Agent

A powerful terminal assistant powered by Google's Gemini AI model that helps you interact with your local environment through natural language.

![Gemini CLI Agent](https://img.shields.io/badge/Gemini-CLI%20Agent-blue)

## Overview

Gemini CLI Agent is a command-line interface tool that connects Google's Gemini AI model with your local system. It allows you to perform file operations, run commands, manage processes, and get intelligent assistance - all using natural language requests.

**Built from scratch** without any AI agent frameworks or libraries - every component is custom-designed for optimal performance and flexibility.

## Features

- **Natural Language System Interaction**: Interact with your system using everyday language
- **File Operations**: Create, read, update, and delete files through AI assistance
- **Directory Management**: Navigate, list, and manipulate directories
- **Command Execution**: Run shell commands and interact with processes
- **Intelligent Context**: System automatically tracks relevant files through vector embeddings
- **Rich Terminal UI**: Beautiful formatting with status indicators and syntax highlighting
- **Smart Context Management**:
  - **Vector Search**: Automatically finds and includes relevant files in AI context
  - **Sticky Files**: Pin important files to always include in AI context regardless of query
  - **File Tracking**: Automatically monitors file changes and updates indexes
- **Mini-Commands**: Quick utilities accessible with backslash commands
- **Conversation History**: Maintains context of your discussion with AI

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/gemini-cli-agent.git
cd gemini-cli-agent
```

2. Install requirements:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Google API key:

4. Run the agent:
```bash
python cliagent_runner.py
```
