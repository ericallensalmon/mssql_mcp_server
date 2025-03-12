import pytest
import pyodbc
import ssl
from mssql_mcp_server import get_connection  # Assuming this is your connection function

def test_connection_encryption():
    """Test that the connection to Azure SQL is encrypted."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check if connection is encrypted
    encryption_result = cursor.execute("""
        SELECT ENCRYPT_OPTION, PROTOCOL_TYPE, AUTH_SCHEME 
        FROM sys.dm_exec_connections 
        WHERE session_id = @@SPID
    """).fetchone()
    
    assert encryption_result.ENCRYPT_OPTION == 'TRUE', "Connection is not encrypted"
    assert encryption_result.PROTOCOL_TYPE == 'TCPIP', "Unexpected protocol type"
    
    cursor.close()
    conn.close()

def test_tls_version():
    """Test that the connection uses TLS 1.2 or higher."""
    conn = get_connection()
    cursor = conn.cursor()
    
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
    conn.close()

def test_connection_properties():
    """Test that required secure connection properties are set."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Check connection properties
    props = {prop.lower(): value for prop, value in conn.getinfo(pyodbc.SQL_SERVER_STATISTICS)}
    
    assert props.get('encrypt') == 'yes', "Connection encryption is not enabled"
    assert props.get('trustservercertificate') in ['yes', 'true'], "Server certificate validation is not properly configured"
    
    cursor.close()
    conn.close()

def test_connection_timeout():
    """Test that connection timeout is properly set."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get connection timeout setting
    timeout = cursor.execute("SELECT @@OPTIONS & 4").fetchval()
    
    assert timeout == 4, "Remote connection timeout is not properly configured"
    
    cursor.close()
    conn.close() 