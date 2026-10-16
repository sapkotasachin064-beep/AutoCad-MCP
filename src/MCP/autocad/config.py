"""Configuration for the AutoCAD MCP server."""

import os

MIN_SUPPORTED_RELEASE = 24.0  # AutoCAD 2021 == internal release 24.0

# Known internal release -> marketing year. AutoCAD exposes no official
# "year" property, only ACADVER release numbers, so this map is best effort
# and extended as new releases ship.
RELEASE_TO_YEAR = {
    24.0: 2021,
    24.1: 2022,
    24.2: 2023,
    24.3: 2024,
    24.4: 2025,
}


def get_output_dir() -> str:
    configured = os.environ.get("AUTOCAD_MCP_OUTPUT_DIR")
    if configured:
        return configured
    return os.path.join(os.path.expanduser("~"), "Documents", "AutoCAD MCP Output")


def get_db_path() -> str:
    configured = os.environ.get("AUTOCAD_MCP_DB_PATH")
    if configured:
        return configured
    return os.path.join(get_output_dir(), "autocad_mcp.db")
