# MSSQL MCP Server

> This is a fork of [mssql_mcp_server](https://github.com/JexinSam/mssql_mcp_server) by [JexinSam](https://github.com/JexinSam). The original project provides a Model Context Protocol server for MSSQL databases.

[![Tests](https://github.com/ericallensalmon/mssql_mcp_server/actions/workflows/test.yml/badge.svg)](https://github.com/ericallensalmon/mssql_mcp_server/actions/workflows/test.yml)

MSSQL MCP Server is a **Model Context Protocol (MCP) server** that enables secure and structured interaction with **Microsoft SQL Server (MSSQL)** databases. It allows AI assistants to:
- List available tables
- Read table contents
- Execute SQL queries with controlled access

This ensures safer database exploration, strict permission enforcement, and logging of database interactions.

## Features

- **Secure MSSQL Database Access** through environment variables
- **Controlled Query Execution** with error handling
- **Table Listing & Data Retrieval**
- **Comprehensive Logging** for monitoring queries and operations

## Installation

If you would like to install a package, please see if the [original](https://github.com/JexinSam/mssql_mcp_server) will work for you first.
```bash
pip install mssql-mcp-server
```

To install this fork instead, you have two options:

1. Install directly from GitHub:
```shell
pip install git+https://github.com/ericallensalmon/mssql_mcp_server.git
```

2. Clone and install locally:
```shell
# Clone the repository
git clone https://github.com/ericallensalmon/mssql_mcp_server.git
cd mssql_mcp_server

# Install the package in editable mode
pip install -e .

# Optional: Install development dependencies if needed (pytest, black, etc.)
pip install -r requirements-dev.txt
```

## Configuration

Set the following environment variables to configure database access:

```bash
MSSQL_DRIVER=mssql_driver
MSSQL_HOST=localhost
MSSQL_USER=your_username
MSSQL_PASSWORD=your_password
MSSQL_DATABASE=your_database
```

## Usage

### With Claude Desktop

To integrate with **Claude Desktop**, add this configuration to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mssql": {
      "command": "uv",
      "args": [
        "--directory",
        "path/to/mssql_mcp_server",
        "run",
        "mssql_mcp_server"
      ],
      "env": {
        "MSSQL_DRIVER": "mssql_driver",
        "MSSQL_HOST": "localhost",
        "MSSQL_USER": "your_username",
        "MSSQL_PASSWORD": "your_password",
        "MSSQL_DATABASE": "your_database"
      }
    }
  }
}
```

### With Cursor AI (requires Agent model with MCP support)
<p style="color: #FFA500; font-weight: bold;">⚠️ Cursor AI does not automatically ignore .env or other files with sensitive keys. By default, files in .cursorignore are not indexed or transmitted, however you can accidentally include them in chat if they are open or with @. A .cursorban file has been discussed but not implemented as of 3/29/2025.</p>

To integrate with **Cursor**, you'll need to set up a virtual environment and install the MCP server locally:

> **Prerequisites**: Python 3.11 or higher is required.

> ⚠️ **Important Note About Environment Variables**  
> While the Claude Desktop configuration above shows environment variables being passed directly in the configuration, this approach doesn't work reliably with Cursor.  
> Instead, we'll use `python-dotenv` to load these from a `.env` file, which provides a more reliable solution.

First, create the necessary directories and set up the virtual environment:

```shell
# Create directories
mkdir -Force .cursor/mcp/mssql-mcp-server

# Create and activate a virtual environment
python -m venv .cursor/venv
.cursor/venv/Scripts/activate

# Install packages
pip install git+https://github.com/ericallensalmon/mssql_mcp_server.git
```

Then create three files:

In the `.cursor` directory, create or add this configuration:
1. `mcp.json`:
```json
{
    "mcpServers": {
        "mssql": {
            "command": "absolute/path/to/.cursor/venv/Scripts/pythonw.exe",
            "args": [
                "absolute/path/to/.cursor/run_server.py"
            ]
        }
    }
} 
```

Add these two files in the `.cursor/mcp/mssql-mcp-server` directory:
1. `run_server.py`:
```python
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Get the absolute path to the directory containing this script
script_dir = Path(__file__).parent.absolute()
os.chdir(script_dir)  # Change to the script directory to ensure relative paths work

# Add the src directory to Python path
src_path = script_dir / "src"
sys.path.insert(0, str(src_path))

# Load environment variables from .env file in the same directory as this script
env_path = script_dir / ".env"
load_dotenv(dotenv_path=env_path)

# Import and run the server
from mssql_mcp_server.server import main
import asyncio

if __name__ == "__main__":
    print(f"Starting server from {script_dir}")
    print(f"Changed working directory to: {os.getcwd()}")
    print(f"Python path: {sys.path}")
    print(f"Environment loaded from: {env_path}")
    asyncio.run(main()) 
```

2. `.env`:
```ini
MSSQL_DRIVER=ODBC Driver 18 for SQL Server
MSSQL_HOST=localhost
MSSQL_USER=your_username
MSSQL_PASSWORD=your_password
MSSQL_DATABASE=your_database
```

After setting up the environment:
1. Edit `.cursor/mcp/mssql-mcp-server/.env` with your actual database credentials
2. Make sure your SQL Server instance is running and accessible
3. Check Cursor Settings -> MCP and verify that the `mssql` MCP server is running and the `execute_sql` tool is available

If needed, test the connection by running `python .cursor/mcp/mssql-mcp-server/run_server.py` from the activated virtual environment

> **Note**: The `pyodbc` package requires the Microsoft ODBC Driver for SQL Server to be installed on your system:
> - **Windows**: Download from [Microsoft Download Center](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
> - **Linux**: Follow [SQL Server installation guide for Linux](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server)
> - **macOS**: Follow [SQL Server installation guide for macOS](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos)
>
> The default driver name in the `.env` file assumes ODBC Driver 18, but you should use whatever version you have installed.

### Running as a Standalone Server

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python -m mssql_mcp_server
```

## Development

```bash
# Clone the repository
git clone https://github.com/ericallensalmon/mssql_mcp_server.git
cd mssql_mcp_server

# Set up a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies
pip install -r requirements-dev.txt

# Run tests
pytest
```

## Security Considerations

- **Use a dedicated MSSQL user** with minimal privileges.
- **Never use root credentials** or full administrative accounts.
- **Restrict database access** to only necessary operations.
- **Enable logging and auditing** for security monitoring.
- **Regularly review permissions** to ensure least privilege access.

## Security Best Practices

For a secure setup:

1. **Create a dedicated MSSQL user** with restricted permissions.
2. **Avoid hardcoding credentials**—use environment variables instead.
3. **Restrict access** to necessary tables and operations only.
4. **Enable SQL Server logging and monitoring** for auditing.
5. **Review database access regularly** to prevent unauthorized access.

For detailed instructions, refer to the **[MSSQL Security Configuration Guide](https://github.com/ericallensalmon/mssql_mcp_server/blob/main/SECURITY.md)**.

⚠️ **IMPORTANT:** Always follow the **Principle of Least Privilege** when configuring database access.

## License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.

## Contributing

For improvements that could benefit the original project, please consider contributing to the [original repository](https://github.com/JexinSam/mssql_mcp_server) first.

For fork-specific features or changes:

1. Create a feature branch: `git checkout -b feature/amazing-feature`
2. Make your changes and ensure tests pass: `python run_tests.py` ([Docker](https://docs.docker.com/get-docker/) required)
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a **Pull Request**

### Maintainer

This fork is maintained by [Eric Salmon](https://github.com/ericallensalmon).

---

### Need Help?

For any questions or issues specific to this fork, feel free to open a GitHub **Issue** in this repository. For general questions about the project, consider posting in the original repository's issue tracker.

