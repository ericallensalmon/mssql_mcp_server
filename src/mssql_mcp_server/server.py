import asyncio
import logging
import os
from pyodbc import connect, Error
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent
from pydantic import AnyUrl

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mssql_mcp_server")

def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "driver": os.getenv("MSSQL_DRIVER", "SQL Server"),
        "server": os.getenv("MSSQL_HOST", "localhost"),
        "user": os.getenv("MSSQL_USER"),
        "password": os.getenv("MSSQL_PASSWORD"),
        "database": os.getenv("MSSQL_DATABASE")
    }
    if not all([config["user"], config["password"], config["database"]]):
        logger.error("Missing required database configuration. Please check environment variables:")
        logger.error("MSSQL_USER, MSSQL_PASSWORD, and MSSQL_DATABASE are required")
        raise ValueError("Missing required database configuration")
    
    
    # Detect if server is Azure SQL based on domain name
    is_azure = ".database.windows.net" in config["server"].lower()
    
    # Build connection string based on server type
    if is_azure:
       # Note: Azure SQL Database manages its own SSL certificates, no need to specify a certificate
        connection_string = (
            f"Driver={config['driver']};"
            f"Server=tcp:{config['server']},1433;"  # Explicit TCP protocol and port
            f"Database={config['database']};"
            f"UID={config['user']};"
            f"PWD={config['password']};"
            "Encrypt=yes;"  # Always encrypt for Azure SQL
            "TrustServerCertificate=no;"  # Validate Azure's SSL certificate
            "Connection Timeout=30;"  # Reasonable timeout
            "ApplicationIntent=ReadWrite;"  # Explicit application intent
            "MultiSubnetFailover=yes;"  # Support for Azure high availability
            "Column Encryption Setting=Enabled;"  # Enable Always Encrypted if configured
        )
    else:
        # Standard SQL Server connection string
        connection_string = f"Driver={config['driver']};Server={config['server']};UID={config['user']};PWD={config['password']};Database={config['database']};"


    return config, connection_string

# Initialize server
app = Server("mssql_mcp_server")

@app.list_resources()
async def list_resources() -> list[Resource]:
    """List MSSQL tables as resources."""
    config, connection_string = get_db_config()
    try:
        with connect(connection_string) as conn:
            with conn.cursor() as cursor:
                # Use INFORMATION_SCHEMA to list tables in MSSQL
                cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';")
                tables = cursor.fetchall()
                logger.info(f"Found tables: {tables}")
                
                resources = []
                for table in tables:
                    resources.append(
                        Resource(
                            uri=f"mssql://{table[0]}/data",
                            name=f"Table: {table[0]}",
                            mimeType="text/plain",
                            description=f"Data in table: {table[0]}"
                        )
                    )
                return resources
    except Error as e:
        logger.error(f"Failed to list resources: {str(e)}")
        return []

@app.read_resource()
async def read_resource(uri: AnyUrl) -> str:
    """Read table contents."""
    config, connection_string = get_db_config()
    uri_str = str(uri)
    logger.info(f"Reading resource: {uri_str}")
    
    if not uri_str.startswith("mssql://"):
        raise ValueError(f"Invalid URI scheme: {uri_str}")
        
    parts = uri_str[8:].split('/')
    table = parts[0]
    
    try:
        with connect(connection_string) as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {table} LIMIT 100")
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                result = [",".join(map(str, row)) for row in rows]
                return "\n".join([",".join(columns)] + result)
                
    except Error as e:
        logger.error(f"Database error reading resource {uri}: {str(e)}")
        raise RuntimeError(f"Database error: {str(e)}")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available MSSQL tools."""
    logger.info("Listing tools...")
    return [
        Tool(
            name="execute_sql",
            description="Execute an SQL query on the MSSQL server",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The SQL query to execute"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="show_tables",
            description="List all tables in the current database",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute SQL commands."""
    config, connection_string = get_db_config()
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    
    try:
        with connect(connection_string) as conn:
            with conn.cursor() as cursor:
                if name == "show_tables":
                    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';")
                    tables = cursor.fetchall()
                    result = [f"Tables_in_{config['database']}"]  # Header
                    result.extend([table[0] for table in tables])
                    return [TextContent(type="text", text="\n".join(result))]
                
                elif name == "execute_sql":
                    query = arguments.get("query")
                    if not query:
                        raise ValueError("Query is required")
                    
                    # Remove comments and whitespace for command detection
                    cleaned_query = "\n".join(
                        line for line in query.splitlines()
                        if not line.strip().startswith('--')
                    ).strip()
                    
                    # Execute the original query (with comments preserved)
                    cursor.execute(query)
                    
                    # Regular SELECT queries
                    if cleaned_query.strip().upper().startswith("SELECT"):
                        columns = [desc[0] for desc in cursor.description]
                        rows = cursor.fetchall()
                        result = [",".join(map(str, row)) for row in rows]
                        return [TextContent(type="text", text="\n".join([",".join(columns)] + result))]
                    
                    # Non-SELECT queries
                    else:
                        conn.commit()
                        return [TextContent(type="text", text=f"Query executed successfully. Rows affected: {cursor.rowcount}")]
                
                else:
                    raise ValueError(f"Unknown tool: {name}")
                    
    except Exception as e:
        logger.error(f"Error executing tool '{name}': {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    """Main entry point to run the MCP server."""
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting MSSQL MCP server...")
    config, _ = get_db_config()
    logger.info(f"Database config: {config['server']}/{config['database']} as {config['user']}")
    
    async with stdio_server() as (read_stream, write_stream):
        try:
            await app.run(
                read_stream,
                write_stream,
                app.create_initialization_options()
            )
        except Exception as e:
            logger.error(f"Server error: {str(e)}", exc_info=True)
            raise

if __name__ == "__main__":
    asyncio.run(main())