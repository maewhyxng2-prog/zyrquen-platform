import os

if os.getenv("PYTHON_DOTENV_DISABLED") != "1":
    from dotenv import load_dotenv

    load_dotenv()
