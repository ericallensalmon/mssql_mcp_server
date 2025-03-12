import pytest
import pyodbc
import ssl
import os
from mssql_mcp_server.server import get_db_config

# Skip all tests in this file if not running against Azure SQL
pytestmark = pytest.mark.skipif(
    not any([
        ".database.windows.net" in os.getenv("MSSQL_HOST", "").lower(),
        os.getenv("FORCE_AZURE_TESTS", "").lower() == "true"
    ]),
    reason="These tests are specific to Azure SQL Database"
)

@pytest.fixture
def db_connection():
    """Fixture to provide database connection."""
    try:
        _, connection_string = get_db_config()
        conn = pyodbc.connect(connection_string)
        yield conn
        conn.close()
    except ValueError as e:
        pytest.skip(f"Database configuration error: {str(e)}")
    except pyodbc.Error as e:
        pytest.skip(f"Database connection error: {str(e)}")

def test_connection_encryption(db_connection):
    """Test that the connection to Azure SQL is encrypted."""
    cursor = db_connection.cursor()
    
    # Check if connection is encrypted
    encryption_result = cursor.execute("""
        SELECT ENCRYPT_OPTION, PROTOCOL_TYPE, AUTH_SCHEME 
        FROM sys.dm_exec_connections 
        WHERE session_id = @@SPID
    """).fetchone()
    
    assert encryption_result.ENCRYPT_OPTION == 'TRUE', "Connection is not encrypted"
    assert encryption_result.PROTOCOL_TYPE == 'TCPIP', "Unexpected protocol type"
    
    cursor.close()

def test_tls_version(db_connection):
    """Test that the connection uses TLS 1.2 or higher."""
    cursor = db_connection.cursor()
    
    # Check TLS version
    tls_result = cursor.execute("""
        SELECT c.encrypt_option,
               c.protocol_type,
               c.auth_scheme,
               c.net_transport,
               c.protocol_version
        FROM sys.dm_exec_connections c
        WHERE c.session_id = @@SPID
    """).fetchone()
    
    assert tls_result.protocol_version >= 0x0303, "TLS version is lower than 1.2"
    
    cursor.close()

def test_connection_properties():
    """Test that required secure connection properties are set."""
    config, connection_string = get_db_config()
    
    # Parse connection string to check security properties
    conn_props = dict(prop.split('=', 1) for prop in connection_string.split(';') if '=' in prop)
    
    # Azure SQL specific checks
    assert conn_props.get('Encrypt', '').lower() == 'yes', "Connection encryption is not enabled"
    assert conn_props.get('TrustServerCertificate', '').lower() == 'no', "Server certificate validation is not properly configured"
    assert conn_props.get('Connection Timeout', '30') == '30', "Connection timeout is not set to 30 seconds"
    assert 'MultiSubnetFailover=yes' in connection_string, "MultiSubnetFailover is not enabled"

def test_azure_specific_settings(db_connection):
    """Test Azure SQL specific security settings."""
    _, connection_string = get_db_config()
    
    # Test Column Encryption setting
    assert 'Column Encryption Setting=Enabled' in connection_string, "Column Encryption Setting is not enabled"
    
    # Test Application Intent
    assert 'ApplicationIntent=ReadWrite' in connection_string, "ApplicationIntent is not set to ReadWrite" 