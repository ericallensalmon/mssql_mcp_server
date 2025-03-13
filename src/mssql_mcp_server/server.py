import asyncio
import logging
import os
import time
import platform
from pyodbc import connect, Error
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent, CallToolResult
from pydantic import AnyUrl, Field
from typing import Optional



# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mssql_mcp_server")

def get_default_driver():
    """Get the default ODBC driver name based on the platform."""
    system = platform.system().lower()
    if system == "windows":
        return "SQL Server"
    elif system == "linux":
        # Try newer drivers first, then fall back to older versions
        for driver in [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server"
        ]:
            try:
                with connect(f"DRIVER={{{driver}}};SERVER=;") as _:
                    return driver
            except:
                continue
        return "ODBC Driver 17 for SQL Server"  # Default to 17 if no driver found
    elif system == "darwin":  # macOS
        return "ODBC Driver 17 for SQL Server"
    else:
        return "SQL Server"  # Generic fallback

# Define transient error codes that should trigger retry
TRANSIENT_ERROR_CODES = {
    '40613',  # Database not currently available
    '40501',  # Service is busy
    '40197',  # Error processing request
    '10928',  # Resource limit reached
    '10929',  # Resource limit reached
    '10053',  # Transport-level error
    '10054',  # Transport-level error
    '10060',  # Network error
    '40143',  # Connection could not be initialized
}

def is_transient_error(e):
    """Check if the error is transient and should be retried."""
    if not hasattr(e, 'args') or not e.args:
        return False
    
    error_msg = str(e.args[0])
    # Extract error code from the message
    for code in TRANSIENT_ERROR_CODES:
        if f"({code})" in error_msg:
            return True
    return False

def retry_on_transient_error(max_attempts=5, initial_delay=1, max_delay=30):
    """Decorator to retry operations on transient errors with exponential backoff."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if not is_transient_error(e) or attempt == max_attempts - 1:
                        raise
                    
                    # Calculate delay with exponential backoff
                    sleep_time = min(delay * (2 ** attempt), max_delay)
                    logger.info(f"Transient error occurred, retrying in {sleep_time} seconds... (Attempt {attempt + 1}/{max_attempts})")
                    time.sleep(sleep_time)
            
            raise last_exception
        return wrapper
    return decorator

@retry_on_transient_error()
def get_db_connection(connection_string):
    """Create a database connection with retry logic."""
    return connect(connection_string)

def get_db_config():
    """Get database configuration from environment variables."""
    config = {
        "driver": os.getenv("MSSQL_DRIVER", get_default_driver()),
        "server": os.getenv("MSSQL_HOST", "localhost"),
        "user": os.getenv("MSSQL_USER"),
        "password": os.getenv("MSSQL_PASSWORD"),
        "database": os.getenv("MSSQL_DATABASE")
    }
    
    logger.info(f"Using SQL Server driver: {config['driver']}")
    
    if not all([config["user"], config["password"], config["database"]]):
        logger.error("Missing required database configuration. Please check environment variables:")
        logger.error("MSSQL_USER, MSSQL_PASSWORD, and MSSQL_DATABASE are required")
        raise ValueError("Missing required database configuration")
    
    # Detect if server is Azure SQL based on domain name
    is_azure = ".database.windows.net" in config["server"].lower()
    
    # Build connection string based on server type
    if is_azure:
        connection_string = (
            f"Driver={{{config['driver']}}};"  # Note the extra braces for Linux ODBC
            f"Server=tcp:{config['server']},1433;"
            f"Database={config['database']};"
            f"UID={config['user']};"
            f"PWD={config['password']};"
            "Encrypt=yes;"
            "TrustServerCertificate=no;"
            "Connection Timeout=30;"
            "ApplicationIntent=ReadWrite;"
            "MultiSubnetFailover=yes;"
            "Column Encryption Setting=Enabled;"
        )
    else:
        connection_string = (
            f"Driver={{{config['driver']}}};"  # Note the extra braces for Linux ODBC
            f"Server={config['server']};"
            f"Database={config['database']};"
            f"UID={config['user']};"
            f"PWD={config['password']};"
        )

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
            name="list_tables",
            description="List all tables in the current database",
            inputSchema={
                "type": "object",
                "properties": {},
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> CallToolResult:
    """Execute SQL commands."""
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    
    # Validate tool name
    if name not in ["execute_sql", "list_tables"]:
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text=f"Error: Unknown tool: {name}"
            )]
        )
    
    # Validate required parameters before attempting database connection
    if name == "execute_sql" and "query" not in arguments:
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text="Error: Query is required"
            )]
        )
    
    # Get database configuration and attempt connection
    try:
        config, connection_string = get_db_config()
        with get_db_connection(connection_string) as conn:
            with conn.cursor() as cursor:
                if name == "list_tables":
                    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';")
                    tables = cursor.fetchall()
                    result = [f"Tables_in_{config['database']}"]  # Header
                    result.extend([table[0] for table in tables])
                    return CallToolResult(
                        content=[TextContent(
                            type="text",
                            text="\n".join(result)
                        )]
                    )
                
                elif name == "execute_sql":
                    query = arguments["query"]  # We already validated it exists
                    
                    # Remove comments and whitespace for command detection
                    cleaned_query = "\n".join(
                        line for line in query.splitlines()
                        if not line.strip().startswith('--')
                    ).strip()
                    
                    try:
                        # Execute the original query (with comments preserved)
                        cursor.execute(query)
                        
                        # For transaction queries, we need to check if there were any errors
                        if "BEGIN TRANSACTION" in cleaned_query.upper():
                            try:
                                # Try to fetch results - this will raise an error if there was a transaction error
                                cursor.fetchall()
                                conn.commit()
                            except Error as e:
                                conn.rollback()
                                return CallToolResult(
                                    isError=True,
                                    content=[TextContent(
                                        type="text",
                                        text=f"Transaction error: {str(e)}"
                                    )]
                                )
                        
                        # Regular SELECT queries
                        if cleaned_query.strip().upper().startswith("SELECT"):
                            columns = [desc[0] for desc in cursor.description]
                            rows = cursor.fetchall()
                            result = [",".join(map(str, row)) for row in rows]
                            return CallToolResult(
                                content=[TextContent(
                                    type="text",
                                    text="\n".join([",".join(columns)] + result)
                                )]
                            )
                        
                        # Non-SELECT queries
                        else:
                            # Check for permission errors (SQL Server error codes)
                            if cursor.messages:
                                for message in cursor.messages:
                                    if any(code in str(message) for code in ['229', '230', '262', '297', '378']):
                                        return CallToolResult(
                                            isError=True,
                                            content=[TextContent(
                                                type="text",
                                                text=f"Permission denied: {str(message)}"
                                            )]
                                        )
                            
                            conn.commit()
                            return CallToolResult(
                                content=[TextContent(
                                    type="text",
                                    text=f"Query executed successfully. Rows affected: {cursor.rowcount}"
                                )]
                            )
                    except Error as e:
                        # SQL-specific errors
                        error_msg = str(e)
                        is_permission_error = any(err in error_msg.lower() for err in 
                            ["permission", "privilege", "access denied", "not authorized"])
                        
                        if is_permission_error:
                            return CallToolResult(
                                isError=True,
                                content=[TextContent(
                                    type="text",
                                    text=f"Permission denied: {error_msg}"
                                )]
                            )
                        
                        return CallToolResult(
                            isError=True,
                            content=[TextContent(
                                type="text",
                                text=f"Error: {error_msg}"
                            )]
                        )
                    
    except Exception as e:
        logger.error(f"Error executing tool '{name}': {e}")
        return CallToolResult(
            isError=True,
            content=[TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]
        )

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