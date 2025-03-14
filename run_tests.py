#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from typing import Dict, Optional

import pyodbc

def get_container_logs(container_name: str) -> str:
    """Get logs from a Docker container."""
    try:
        result = subprocess.run(
            f'docker ps -q --filter "ancestor={container_name}"',
            shell=True,
            check=True,
            text=True,
            capture_output=True
        )
        container_id = result.stdout.strip()
        if container_id:
            log_result = subprocess.run(
                f"docker logs {container_id}",
                shell=True,
                check=True,
                text=True,
                capture_output=True
            )
            return log_result.stdout
    except Exception as e:
        return f"Error getting logs: {e}"
    return ""

def wait_for_sql_server(password: str, container_name: str, port: int = 1433, timeout_seconds: int = 120) -> bool:
    """Wait for SQL Server to be ready."""
    print(f"Waiting for SQL Server to be ready on port {port}...")
    start_time = time.time()
    last_log_check = 0
    
    while True:
        try:
            # Explicit connection string with port
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER=127.0.0.1,{port};"  # Use explicit IP and port
                f"DATABASE=master;"
                f"UID=sa;"
                f"PWD={password};"
                f"TrustServerCertificate=yes;"
                f"Encrypt=yes;"
                f"ConnectTimeout=5"  # Short timeout for faster retry
            )
            print(f"\nAttempting connection to 127.0.0.1:{port}")
            conn = pyodbc.connect(conn_str)
            conn.close()
            print(f"SQL Server is ready on port {port}!")
            return True
        except Exception as e:
            elapsed_time = time.time() - start_time
            current_time = time.time()
            
            # Print error and logs every 10 seconds
            if current_time - last_log_check >= 10:
                print(f"\nConnection error ({int(elapsed_time)}s): {str(e)}")
                print("\nContainer logs:")
                print(get_container_logs(container_name))
                last_log_check = current_time
            
            if elapsed_time > timeout_seconds:
                print(f"\nTimeout waiting for SQL Server on port {port} after {timeout_seconds} seconds")
                print(f"Last error: {str(e)}")
                print("\nFinal container logs:")
                print(get_container_logs(container_name))
                return False
            
            print(f"Waiting for SQL Server to be ready on port {port}... ({int(elapsed_time)}s)", end="\r")
            time.sleep(1)

def run_command(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command."""
    print(f"Running command: {cmd}")
    return subprocess.run(cmd, shell=True, check=check, text=True)

def run_tests(env_vars: Dict[str, str], test_args: str) -> int:
    """Run pytest with the specified environment variables and arguments."""
    test_env = os.environ.copy()
    test_env.update(env_vars)
    
    try:
        print(f"\nRunning tests with arguments: {test_args}")
        print("Environment variables:")
        for key, value in env_vars.items():
            print(f"  {key}={value}")
        
        print("\nCollecting and running tests...")
        # Add timeout and progress indicators
        result = subprocess.run(
            f"python -m pytest {test_args} -vv --tb=short --showlocals --color=yes --timeout=30 --timeout-method=thread -p no:warnings",
            shell=True,
            env=test_env,
            check=False,
            text=True,
            capture_output=True
        )
        
        # Always print the test output
        if result.stdout:
            print("\nTest output:")
            print(result.stdout)
        if result.stderr:
            print("\nTest errors:")
            print(result.stderr)
            
        if result.returncode != 0:
            print("\n" + "="*80)
            print("Test Failure Summary")
            print("="*80)
            
            print("\nRunning just the failed tests...")
            # Run pytest again with just the failed tests for a cleaner output
            failure_result = subprocess.run(
                f"python -m pytest {test_args} --lf -vv --tb=short --showlocals --color=yes --timeout=30 --timeout-method=thread",
                shell=True,
                env=test_env,
                check=False,
                text=True,
                capture_output=True
            )
            
            if failure_result.stdout:
                print(failure_result.stdout)
            if failure_result.stderr:
                print(failure_result.stderr)
            
            print("\nDetailed failure information:")
            # Run one more time with full traceback for detailed error info
            detail_result = subprocess.run(
                f"python -m pytest {test_args} --lf -vv --tb=long --showlocals --color=yes --timeout=30 --timeout-method=thread",
                shell=True,
                env=test_env,
                check=False,
                text=True,
                capture_output=True
            )
            
            if detail_result.stdout:
                print(detail_result.stdout)
            if detail_result.stderr:
                print(detail_result.stderr)
            
        print(f"\nTest return code: {result.returncode}")
        return result.returncode
    except Exception as e:
        print(f"Error running tests: {e}")
        return 1

def stop_container(container_name: str) -> None:
    """Stop a Docker container by its name/ancestor."""
    try:
        # Get container ID using PowerShell syntax
        result = subprocess.run(
            f'docker ps -q --filter "ancestor={container_name}"',
            shell=True,
            check=True,
            text=True,
            capture_output=True
        )
        container_id = result.stdout.strip()
        if container_id:
            run_command(f"docker stop {container_id}", check=False)
    except Exception as e:
        print(f"Error stopping container {container_name}: {e}")

def cleanup_containers(container_name: str) -> None:
    """Clean up Docker containers by ancestor name."""
    try:
        # First stop any running containers
        stop_container(container_name)
        
        # PowerShell-compatible command to get container IDs
        result = subprocess.run(
            f'docker ps -a -q --filter "ancestor={container_name}"',
            shell=True,
            check=True,
            text=True,
            capture_output=True
        )
        container_ids = result.stdout.strip().split('\n')
        for container_id in container_ids:
            if container_id:
                print(f"Removing container {container_id}")
                run_command(f"docker rm -f {container_id}", check=False)
    except Exception as e:
        print(f"Error cleaning up containers for {container_name}: {e}")

def pause_on_failure(container_name: str) -> None:
    """Pause execution if there's a failure to allow container examination."""
    try:
        # Get container ID
        result = subprocess.run(
            f'docker ps -q --filter "ancestor={container_name}"',
            shell=True,
            check=True,
            text=True,
            capture_output=True
        )
        container_id = result.stdout.strip()
        
        print(f"\nTest failure detected. Container '{container_name}' (ID: {container_id}) is still running.")
        print("\nUseful debugging commands:")
        print(f"1. View container logs:")
        print(f"   docker logs {container_id}")
        print(f"\n2. View container status:")
        print(f"   docker inspect {container_id}")
        print(f"\n3. Connect to SQL Server:")
        print(f"   docker exec -it {container_id} /opt/mssql-tools/bin/sqlcmd -U sa -P <password>")
        print(f"\n4. View container resource usage:")
        print(f"   docker stats {container_id} --no-stream")
        print(f"\n5. Shell into container:")
        print(f"   docker exec -it {container_id} bash")
        
        # Show current container logs
        print("\nCurrent container logs:")
        print(get_container_logs(container_name))
        
        input("\nPress Enter to cleanup and continue, or Ctrl+C to abort...")
    except Exception as e:
        print(f"Error getting container information: {e}")
        input("Press Enter to cleanup and continue...")

def main() -> int:
    mssql2019_result = 1
    azure_sql_result = 1

    try:
        # Clean up any existing containers first
        print("\nCleaning up any existing containers...")
        cleanup_containers("mssql2019-test")
        cleanup_containers("azuresqledge-test")

        # Install dependencies including pytest
        print("\nInstalling dependencies...")
        run_command("python -m pip install --upgrade pip")
        run_command("python -m pip install pytest pytest-sugar pytest-clarity pytest-timeout")
        run_command("python -m pip install -r requirements.txt")
        run_command("python -m pip install -r requirements-dev.txt")
        run_command("python -m pip install -e .")

        # Test SQL Server 2019
        try:
            print("\nTesting with SQL Server 2019...")
            run_command("docker build --target mssql2019 -t mssql2019-test .")
            run_command('docker run -d -p 1433:1433 --memory 2g --memory-reservation 2g -e "ACCEPT_EULA=Y" -e "MSSQL_SA_PASSWORD=P@ssw0rd2024" -e "MSSQL_PID=Developer" mssql2019-test')

            mssql2019_env = {
                "MSSQL_HOST": "127.0.0.1",
                "MSSQL_USER": "sa",
                "MSSQL_PASSWORD": "P@ssw0rd2024",
                "MSSQL_DATABASE": "master",
                "MSSQL_DRIVER": "ODBC Driver 17 for SQL Server",
                "MSSQL_PORT": "1433",
                "MSSQL_CONNECT_TIMEOUT": "30",
                "MSSQL_TRUST_SERVER_CERTIFICATE": "yes"
            }

            if wait_for_sql_server(mssql2019_env["MSSQL_PASSWORD"], "mssql2019-test"):
                mssql2019_result = run_tests(mssql2019_env, "-v tests --ignore=tests/test_azure_sql_security.py")
                if mssql2019_result != 0:
                    print("\nSQL Server 2019 tests failed!")
                    pause_on_failure("mssql2019-test")
        except Exception as e:
            print(f"\nError during SQL Server 2019 tests: {e}")
            pause_on_failure("mssql2019-test")
        finally:
            if mssql2019_result == 0:
                print("\nCleaning up SQL Server 2019 container...")
                stop_container("mssql2019-test")
                cleanup_containers("mssql2019-test")
            else:
                print("\nSkipping cleanup due to test failure. Container left running for inspection.")

        # Test Azure SQL Edge
        try:
            print("\nTesting with Azure SQL Edge...")
            run_command("docker build --target azuresqledge -t azuresqledge-test .")
            run_command('docker run -d'
                      ' -p 1433:1433'  # Map to default SQL Server port
                      ' --memory 2g --memory-reservation 2g'
                      ' -e "ACCEPT_EULA=Y"'
                      ' -e "MSSQL_SA_PASSWORD=TestPassword123!"'
                      ' -e "MSSQL_PID=Developer"'
                      ' -e "MSSQL_TCP_PORT=1433"'  # Use default port internally
                      ' -e "MSSQL_IP_ADDRESS=0.0.0.0"'
                      ' --hostname sql1'
                      ' --name azuresqledge-test'
                      ' azuresqledge-test')

            azure_sql_env = {
                "MSSQL_HOST": "127.0.0.1",  # Use explicit IP
                "MSSQL_USER": "sa",
                "MSSQL_PASSWORD": "TestPassword123!",
                "MSSQL_DATABASE": "master",
                "MSSQL_DRIVER": "ODBC Driver 17 for SQL Server",
                "MSSQL_PORT": "1433",  # Use default port
                "MSSQL_CONNECT_TIMEOUT": "30",
                "MSSQL_TRUST_SERVER_CERTIFICATE": "yes"
            }

            # Wait longer for Azure SQL Edge
            if wait_for_sql_server(azure_sql_env["MSSQL_PASSWORD"], "azuresqledge-test", port=1433, timeout_seconds=180):
                azure_sql_result = run_tests(azure_sql_env, "-v tests")
                if azure_sql_result != 0:
                    print("\nAzure SQL Edge tests failed!")
                    pause_on_failure("azuresqledge-test")
        except Exception as e:
            print(f"\nError during Azure SQL Edge tests: {e}")
            pause_on_failure("azuresqledge-test")
        finally:
            if azure_sql_result == 0:
                print("\nCleaning up Azure SQL Edge container...")
                stop_container("azuresqledge-test")
                cleanup_containers("azuresqledge-test")
            else:
                print("\nSkipping cleanup due to test failure. Container left running for inspection.")

    except Exception as e:
        print(f"\nError during test execution: {e}")
        return 1
    finally:
        # Report results
        print("\nTest Results:")
        print(f"SQL Server 2019 Tests: {'PASSED' if mssql2019_result == 0 else 'FAILED'}")
        print(f"Azure SQL Edge Tests: {'PASSED' if azure_sql_result == 0 else 'FAILED'}")

    return 1 if mssql2019_result != 0 or azure_sql_result != 0 else 0

if __name__ == "__main__":
    sys.exit(main()) 