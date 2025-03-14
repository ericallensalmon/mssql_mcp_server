import asyncio
import logging
import os
import time
import platform
from pyodbc import connect, Error
from mcp.server import Server
from mcp.types import Resource, Tool, TextContent, ImageContent, EmbeddedResource, CallToolResult
from pydantic import AnyUrl, Field
from typing import Optional, List, Union, Sequence



# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
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
    logger.info("Attempting database connection...")
    try:
        conn = connect(connection_string)
        logger.info("Database connection successful")
        return conn
    except Exception as e:
        logger.error(f"Connection error in get_db_connection: {str(e)}")
        logger.error(f"Connection error type: {type(e)}")
        logger.error(f"Connection string (sanitized): {connection_string.replace(connection_string.split('PWD=')[1].split(';')[0], '***')}")
        raise

def get_db_config():
    """Get database configuration from environment variables."""
    logger.info("Getting database configuration...")
    config = {
        "driver": os.getenv("MSSQL_DRIVER", get_default_driver()),
        "server": os.getenv("MSSQL_HOST", "localhost"),
        "user": os.getenv("MSSQL_USER"),
        "password": "***",  # Masked for logging
        "database": os.getenv("MSSQL_DATABASE")
    }
    
    logger.info(f"Configuration loaded:")
    logger.info(f"  Driver: {config['driver']}")
    logger.info(f"  Server: {config['server']}")
    logger.info(f"  Database: {config['database']}")
    logger.info(f"  User: {config['user']}")
    
    # Get actual password for connection
    config["password"] = os.getenv("MSSQL_PASSWORD")
    
    if not all([config["user"], config["password"], config["database"]]):
        missing = []
        if not config["user"]: missing.append("MSSQL_USER")
        if not config["password"]: missing.append("MSSQL_PASSWORD")
        if not config["database"]: missing.append("MSSQL_DATABASE")
        logger.error(f"Missing required configuration: {', '.join(missing)}")
        raise ValueError("Missing required database configuration")
    
    # Detect if server is Azure SQL based on domain name
    is_azure = ".database.windows.net" in config["server"].lower()
    logger.info(f"Azure SQL Server detected: {is_azure}")
    
    # Build connection string based on server type
    if is_azure:
        connection_string = (
            f"Driver={{{config['driver']}}};"
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
            f"Driver={{{config['driver']}}};"
            f"Server={config['server']};"
            f"Database={config['database']};"
            f"UID={config['user']};"
            f"PWD={config['password']};"
        )
    
    # Log sanitized connection string
    logger.info(f"Connection string (sanitized): {connection_string.replace(config['password'], '***')}")
    
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
async def call_tool(name: str, arguments: dict) -> Sequence[TextContent]:
    """Execute SQL commands."""
    logger.info(f"Calling tool: {name} with arguments: {arguments}")
    
    # Validate tool name
    if name not in ["execute_sql", "list_tables"]:
        return [TextContent(
            type="text",
            text=f"Unknown tool: {name}"
        )]
    
    # Validate required parameters before attempting database connection
    if name == "execute_sql" and "query" not in arguments:
        return [TextContent(
            type="text",
            text="Error: Query is required"
        )]
    
    # Get database configuration and attempt connection
    try:
        logger.info("Getting database configuration for tool execution...")
        config, connection_string = get_db_config()
        
        logger.info("Attempting to establish database connection...")
        with get_db_connection(connection_string) as conn:
            logger.info("Database connection established successfully")
            with conn.cursor() as cursor:
                if name == "list_tables":
                    logger.info("Executing list_tables query...")
                    try:
                        cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';")
                        tables = cursor.fetchall()
                        logger.info(f"Found {len(tables)} tables")
                        result = [f"Tables_in_{config['database']}"]
                        result.extend([table[0] for table in tables])
                        return [TextContent(
                            type="text",
                            text="\n".join(result)
                        )]
                    except Exception as e:
                        logger.error(f"Error in list_tables: {str(e)}")
                        logger.error(f"Error type: {type(e)}")
                        return [TextContent(
                            type="text",
                            text=f"Error listing tables: {str(e)}"
                        )]
                
                elif name == "execute_sql":
                    query = arguments["query"]
                    logger.info(f"Executing SQL query: {query}")
                    
                    # Remove comments and whitespace for command detection
                    cleaned_query = "\n".join(
                        line for line in query.splitlines()
                        if not line.strip().startswith('--')
                    ).strip()
                    
                    try:
                        # For transaction queries, we need to check if there were any errors
                        if "BEGIN TRANSACTION" in cleaned_query.upper():
                            try:
                                # Execute each statement in the transaction separately
                                statements = [s.strip() for s in cleaned_query.split(';') if s.strip()]
                                for stmt in statements:
                                    if stmt.upper().startswith('BEGIN TRANSACTION'):
                                        continue
                                    if stmt.upper().startswith('COMMIT'):
                                        conn.commit()
                                        continue
                                    cursor.execute(stmt)
                                    # Try to fetch results to detect errors
                                    try:
                                        cursor.fetchall()
                                    except:
                                        pass  # Ignore fetch errors for non-SELECT statements
                                
                                # If we got here, all statements succeeded
                                return [TextContent(
                                    type="text",
                                    text="Transaction completed successfully"
                                )]
                            except Error as e:
                                conn.rollback()
                                return [TextContent(
                                    type="text",
                                    text=f"Transaction error: {str(e)}"
                                )]
                        
                        # Execute the query
                        cursor.execute(query)
                        
                        # Check for permission errors in cursor messages
                        if cursor.messages:
                            for message in cursor.messages:
                                msg_str = str(message)
                                if any(code in msg_str for code in ['229', '230', '262', '297', '378']):
                                    return [TextContent(
                                        type="text",
                                        text=f"Permission denied: {msg_str}"
                                    )]
                        
                        # Regular SELECT queries
                        if cleaned_query.strip().upper().startswith("SELECT"):
                            logger.info("Processing SELECT query results...")
                            
                            # Get column info
                            columns = [desc[0] for desc in cursor.description]
                            logger.info(f"Query columns: {columns}")
                            
                            # Fetch rows
                            rows = cursor.fetchall()
                            logger.info(f"Raw query results: {rows}")
                            
                            # Process rows
                            result = []
                            for row in rows:
                                row_str = ",".join(map(str, row))
                                logger.info(f"Processing row: {row_str}")
                                result.append(row_str)
                            
                            # Build final text
                            header = ",".join(columns)
                            logger.info(f"Header: {header}")
                            result_text = "\n".join([header] + result)
                            logger.info(f"Final result text: {result_text}")
                            
                            return [TextContent(
                                type="text",
                                text=result_text
                            )]
                        
                        # Non-SELECT queries
                        else:
                            conn.commit()
                            result_text = f"Query executed successfully. Rows affected: {cursor.rowcount}"
                            logger.info(f"Query result: {result_text}")
                            
                            return [TextContent(
                                type="text",
                                text=result_text
                            )]
                    except Error as e:
                        # SQL-specific errors
                        error_msg = str(e)
                        
                        # Check for permission errors in both error message and cursor messages
                        is_permission_error = (
                            any(err in error_msg.lower() for err in 
                                ["permission", "privilege", "access denied", "not authorized"]) or
                            (cursor.messages and any(
                                any(err in str(msg).lower() for err in 
                                    ["permission", "privilege", "access denied", "not authorized"])
                                for msg in cursor.messages
                            ))
                        )
                        
                        if is_permission_error:
                            return [TextContent(
                                type="text",
                                text=f"Permission denied: {error_msg}"
                            )]
                        
                        return [TextContent(
                            type="text",
                            text=f"Error: {error_msg}"
                        )]
                    
    except Exception as e:
        logger.error(f"Error executing tool '{name}': {str(e)}")
        logger.error(f"Error type: {type(e)}")
        logger.error(f"Error location: {e.__traceback__.tb_frame.f_code.co_filename}:{e.__traceback__.tb_lineno}")
        return [TextContent(
            type="text",
            text=f"Error: {str(e)}"
        )]

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