import subprocess
import sys

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def main():
    # Install required packages
    with open('requirements.txt', 'r') as f:
        packages = f.read().splitlines()
        for package in packages:
            install(package)
    
    # Install Playwright browsers
    subprocess.check_call([sys.executable, "-m", "playwright", "install"])

if __name__ == "__main__":
    main()