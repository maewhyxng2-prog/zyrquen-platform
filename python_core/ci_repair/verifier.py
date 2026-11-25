import subprocess

def run_verification_tests() -> bool:
    """Runs pytest on python_core tests to verify if code changes resolved the issues successfully."""
    print("Running local pytest validation suite...")
    try:
        # Run pytest inside python_core directory
        result = subprocess.run(
            ["pytest", "python_core/"],
            capture_output=True,
            text=True,
            cwd="/content/zyrquen-platform",
            timeout=60
        )
        print(result.stdout)
        if result.returncode == 0:
            print("Verification successful: All tests passed.")
            return True
        else:
            print("Verification failed: Some tests did not pass.")
            return False
    except Exception as e:
        print(f"Verification execution failed: {e}")
        return False
