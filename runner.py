import os
import subprocess
import sys


def main():
    port = os.environ.get("CDSW_APP_PORT", "8080")

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.port",
            port,
            "--server.address",
            "127.0.0.1",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()