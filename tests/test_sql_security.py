import pytest
import pyodbc
import ssl
import os
from mssql_mcp_server.server import get_db_config

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

def test_tls_version_and_cipher(db_connection):
    """Test that the connection uses TLS 1.2 or higher with secure cipher suites."""
    cursor = db_connection.cursor()
    
    # Check TLS version and cipher details using DMV
    tls_result = cursor.execute("""
        SELECT 
            c.encrypt_option,
            c.protocol_type,
            c.auth_scheme,
            c.net_transport,
            c.protocol_version,
            c.net_packet_size,
            c.client_net_address,
            c.client_tcp_port,
            c.local_net_address,
            c.local_tcp_port
        FROM sys.dm_exec_connections c
        WHERE c.session_id = @@SPID
    """).fetchone()
    
    # Check for disabled protocols
    disabled_protocols = cursor.execute("""
        SELECT value_name, value_data
        FROM sys.dm_server_registry
        WHERE registry_key LIKE '%Protocols%'
        AND (value_name LIKE '%Named Pipes%' OR value_name LIKE '%Shared Memory%')
    """).fetchall()
    
    # Verify encryption is enabled
    assert tls_result.encrypt_option == 'TRUE', "Connection is not encrypted"
    
    # Verify TCP transport
    assert tls_result.net_transport == 'TCP', "Connection must use TCP transport"
    
    # Verify reasonable packet size
    assert tls_result.net_packet_size <= 32768, "Packet size exceeds secure threshold"
    
    # Verify we're using TCP ports (not named pipes or shared memory)
    assert tls_result.client_tcp_port is not None, "Client TCP port not set"
    assert tls_result.local_tcp_port is not None, "Local TCP port not set"
    
    # Verify TLS version (0x0303 for TLS 1.2, 0x0304 for TLS 1.3)
    assert tls_result.protocol_version >= 0x0303, "TLS version is lower than 1.2"
    
    # Verify insecure protocols are disabled
    for protocol in disabled_protocols:
        assert protocol.value_data == '0', f"Insecure protocol enabled: {protocol.value_name}"
    
    cursor.close()

def test_connection_properties():
    """Test that required secure connection properties are set."""
    config, connection_string = get_db_config()
    
    # Parse connection string to check security properties
    conn_props = dict(prop.split('=', 1) for prop in connection_string.split(';') if '=' in prop)
    
    # Get expected trust certificate setting from environment
    trust_server_cert = os.getenv("MSSQL_TRUST_SERVER_CERTIFICATE", "").lower() != "no"
    expected_trust_value = "yes" if trust_server_cert else "no"
    
    # Security checks for all SQL Server variants
    assert conn_props.get('Encrypt', '').lower() == 'yes', "Connection encryption is not enabled"
    assert conn_props.get('TrustServerCertificate', '').lower() == expected_trust_value, \
        f"TrustServerCertificate setting does not match environment configuration (expected: {expected_trust_value})"
    assert conn_props.get('Connection Timeout', '30') == '30', "Connection timeout is not set to 30 seconds"
    assert 'MultiSubnetFailover=yes' in connection_string, "MultiSubnetFailover is not enabled"
    assert 'ApplicationIntent=ReadWrite' in connection_string, "ApplicationIntent is not set to ReadWrite"
    assert conn_props.get('Protocol', '').upper() == 'TCP', "Protocol must be set to TCP"

def test_authentication_security(db_connection):
    """Test authentication and session security settings."""
    cursor = db_connection.cursor()
    
    # Check authentication and session settings
    auth_result = cursor.execute("""
        SELECT 
            c.auth_scheme,
            s.ansi_nulls,
            s.quoted_identifier,
            s.arithabort
        FROM sys.dm_exec_connections c
        JOIN sys.dm_exec_sessions s ON c.session_id = s.session_id
        WHERE c.session_id = @@SPID
    """).fetchone()
    
    # Verify authentication scheme
    assert auth_result.auth_scheme in ['SQL', 'NTLM', 'KERBEROS'], "Unsupported authentication scheme"
    
    # Verify secure session properties
    assert auth_result.ansi_nulls == 1, "ANSI_NULLS must be enabled"
    assert auth_result.quoted_identifier == 1, "QUOTED_IDENTIFIER must be enabled"
    
    cursor.close() 