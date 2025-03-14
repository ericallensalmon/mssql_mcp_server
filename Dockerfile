# SQL Server 2019 Environment
FROM mcr.microsoft.com/mssql/server:2019-latest AS mssql2019
ENV ACCEPT_EULA=Y
ENV MSSQL_PID=Developer
ENV MSSQL_SA_PASSWORD=P@ssw0rd2024
ENV MSSQL_TCP_PORT=1433

# Azure SQL Edge Environment
FROM mcr.microsoft.com/azure-sql-edge:latest AS azuresqledge
ENV ACCEPT_EULA=Y
ENV MSSQL_SA_PASSWORD=TestPassword123!
ENV MSSQL_TCP_PORT=1434


# Note: You can build and run these images separately using:
# For SQL Server 2019:
# docker build --target mssql2019 -t mssql2019-test .
# docker run -p 1433:1433 mssql2019-test

# For Azure SQL Edge:
# docker build --target azuresqledge -t azuresqledge-test .
# docker run -p 1434:1434 azuresqledge-test 