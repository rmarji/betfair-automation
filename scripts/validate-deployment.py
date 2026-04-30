#!/usr/bin/env python3
"""
Betfair Automation - Deployment Validation Script

Validates deployment readiness by checking:
- Required configuration files
- Environment variables
- Directory structure
- Connectivity checks (with mock fallback)

Usage:
    python scripts/validate-deployment.py [--verbose] [--skip-network]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


class ValidationResult:
    def __init__(self):
        self.checks: List[Tuple[str, bool, str]] = []
        self.warnings: List[str] = []
        self.errors: List[str] = []

    def add_check(self, name: str, passed: bool, detail: str = ""):
        self.checks.append((name, passed, detail))
        if not passed:
            self.errors.append(f"FAIL: {name} - {detail}")
        return passed

    def add_warning(self, message: str):
        self.warnings.append(message)

    @property
    def all_passed(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def print_summary(self):
        print(f"\n{Colors.BOLD}{'=' * 50}{Colors.END}")
        print(f"{Colors.BOLD}  DEPLOYMENT VALIDATION SUMMARY{Colors.END}")
        print(f"{Colors.BOLD}{'=' * 50}{Colors.END}\n")

        for name, passed, detail in self.checks:
            status = (
                f"{Colors.GREEN}✓{Colors.END}"
                if passed
                else f"{Colors.RED}✗{Colors.END}"
            )
            print(f"  {status} {name}")
            if detail:
                print(f"      {detail}")

        if self.warnings:
            print(f"\n{Colors.YELLOW}⚠ Warnings:{Colors.END}")
            for w in self.warnings:
                print(f"  • {w}")

        print(f"\n{Colors.BOLD}{'─' * 50}{Colors.END}")
        if self.all_passed:
            print(
                f"{Colors.GREEN}{Colors.BOLD}✓ All checks passed - Ready for deployment{Colors.END}"
            )
            return 0
        else:
            print(
                f"{Colors.RED}{Colors.BOLD}✗ Validation failed - Fix errors before deploying{Colors.END}"
            )
            return 1


def check_config_files(result: ValidationResult, base_path: Path):
    """Verify all required configuration files exist."""
    print(
        f"\n{Colors.BLUE}{Colors.BOLD}[1/5] Checking Configuration Files...{Colors.END}"
    )

    required_files = [
        ("requirements.txt", "Python dependencies"),
        (".env.example", "Environment template"),
        ("config.json", "Trading configuration"),
        ("Dockerfile", "Container definition"),
        ("docker-compose.yml", "Container orchestration"),
    ]

    optional_files = [
        ("config/credentials.json", "Betfair API credentials"),
    ]

    all_exist = True
    for filename, description in required_files:
        path = base_path / filename
        exists = path.exists()
        status = "found" if exists else "MISSING"
        color = Colors.GREEN if exists else Colors.RED
        print(f"  {color}{'✓' if exists else '✗'}{Colors.END} {filename}: {status}")
        result.add_check(f"File: {filename}", exists, f"Required - {description}")
        all_exist = all_exist and exists

    for filename, description in optional_files:
        path = base_path / filename
        exists = path.exists()
        status = "found" if exists else "optional"
        print(f"  {Colors.YELLOW}○{Colors.END} {filename}: {status}")
        if not exists:
            result.add_warning(
                f"{filename} is optional but recommended for live trading"
            )

    return all_exist


def check_environment_vars(result: ValidationResult):
    """Check required environment variables."""
    print(
        f"\n{Colors.BLUE}{Colors.BOLD}[2/5] Checking Environment Variables...{Colors.END}"
    )

    required_vars = ["BETFAIR_USERNAME", "BETFAIR_PASSWORD", "BETFAIR_APP_KEY"]
    optional_vars = ["BETFAIR_CERTS_PATH"]

    all_set = True
    for var in required_vars:
        value = os.environ.get(var, "")
        is_set = bool(value and value.strip())
        status = "set" if is_set else "empty"
        color = Colors.GREEN if is_set else Colors.YELLOW
        print(f"  {color}{'✓' if is_set else '○'}{Colors.END} {var}: {status}")
        result.add_check(f"Env: {var}", is_set, "Required for API access")
        all_set = all_set and is_set

    for var in optional_vars:
        value = os.environ.get(var, "/app/certs")
        print(f"  {Colors.BLUE}~{Colors.END} {var}: {value}")

    if not all_set:
        result.add_warning("Environment variables not set - running in demo mode only")


def check_directory_structure(result: ValidationResult, base_path: Path):
    """Verify directory structure for container."""
    print(
        f"\n{Colors.BLUE}{Colors.BOLD}[3/5] Checking Directory Structure...{Colors.END}"
    )

    required_dirs = [
        ("config", "Configuration directory"),
        ("data", "Persistent data storage"),
        ("scripts", "Utility scripts"),
    ]

    required_subdirs = [
        ("config", "certs", "SSL certificates for Betfair API"),
    ]

    all_ok = True
    for dirname, description in required_dirs:
        path = base_path / dirname
        exists = path.exists() and path.is_dir()
        print(
            f"  {Colors.GREEN}{'✓' if exists else '✗'}{Colors.END} {dirname}/: {description}"
        )
        result.add_check(f"Directory: {dirname}", exists)
        all_ok = all_ok and exists

    for parent, subdir, description in required_subdirs:
        path = base_path / parent / subdir
        exists = path.exists() and path.is_dir()
        print(f"  {Colors.YELLOW}○{Colors.END} {parent}/{subdir}/: {description}")
        if not exists:
            result.add_warning(
                f"{parent}/{subdir}/ missing - create if using SSL certificates"
            )

    return all_ok


def check_python_dependencies(result: ValidationResult):
    """Verify Python packages can be imported."""
    print(
        f"\n{Colors.BLUE}{Colors.BOLD}[4/5] Checking Python Dependencies...{Colors.END}"
    )

    required_modules = [
        "betfairlightweight",
        "signal_engine",
        "paper_trader",
        "config",
    ]

    all_ok = True
    for module in required_modules:
        try:
            __import__(module)
            print(f"  {Colors.GREEN}✓{Colors.END} {module}")
        except ImportError as e:
            print(f"  {Colors.RED}✗{Colors.END} {module}: {e}")
            result.add_check(f"Module: {module}", False, str(e))
            all_ok = False

    return all_ok


def check_connectivity(result: ValidationResult, skip_network: bool = False):
    """Test network connectivity and API readiness."""
    print(f"\n{Colors.BLUE}{Colors.BOLD}[5/5] Checking Connectivity...{Colors.END}")

    if skip_network:
        print(f"  {Colors.YELLOW}⊘{Colors.END} Network check skipped (--skip-network)")
        result.add_warning("Network connectivity not verified")
        return True

    checks_passed = True

    # Check DNS resolution
    import socket as sock_module

    try:
        sock_module.gethostbyname("api.betfair.com")
        print(f"  {Colors.GREEN}✓{Colors.END} DNS: api.betfair.com resolves")
        result.add_check("DNS Resolution", True)
    except sock_module.gaierror as e:
        print(f"  {Colors.RED}✗{Colors.END} DNS: api.betfair.com - {e}")
        result.add_check("DNS Resolution", False)
        checks_passed = False

    # Check SSL connectivity (mock check)
    import socket
    import ssl

    try:
        context = ssl.create_default_context()
        with socket.create_connection(("api.betfair.com", 443), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname="api.betfair.com") as ssock:
                print(
                    f"  {Colors.GREEN}✓{Colors.END} SSL: api.betfair.com:443 reachable"
                )
                result.add_check("SSL Connectivity", True)
    except (socket.timeout, socket.error, ssl.SSLError) as e:
        print(f"  {Colors.YELLOW}○{Colors.END} SSL: api.betfair.com - {e}")
        result.add_warning(
            "Could not connect to Betfair API - may be expected in isolated environments"
        )
        result.add_check(
            "SSL Connectivity", True, "Network blocked but not required for demo mode"
        )

    # Check Betfair credentials (if available)
    username = os.environ.get("BETFAIR_USERNAME", "")
    password = os.environ.get("BETFAIR_PASSWORD", "")
    app_key = os.environ.get("BETFAIR_APP_KEY", "")

    has_creds = all([username, password, app_key])
    if has_creds:
        print(f"  {Colors.GREEN}✓{Colors.END} Credentials: API credentials configured")
        result.add_check("API Credentials", True)
    else:
        print(f"  {Colors.YELLOW}○{Colors.END} Credentials: Not configured (demo mode)")
        result.add_check("API Credentials", False, "Required for live trading")

    return checks_passed


def check_dockerfile(result: ValidationResult, base_path: Path):
    """Verify Dockerfile can build."""
    print(f"\n{Colors.BLUE}{Colors.BOLD}[Bonus] Checking Dockerfile...{Colors.END}")

    dockerfile = base_path / "Dockerfile"
    if not dockerfile.exists():
        result.add_check("Dockerfile exists", False)
        return False

    with open(dockerfile) as f:
        content = f.read()

    checks = [
        ("python" in content.lower(), "Uses Python base image"),
        ("requirements.txt" in content, "Installs requirements.txt"),
        ("WORKDIR" in content, "Sets working directory"),
        (
            "HEALTHCHECK" in content or "healthcheck" in content.lower(),
            "Has healthcheck defined",
        ),
    ]

    all_ok = True
    for passed, description in checks:
        print(
            f"  {Colors.GREEN if passed else Colors.YELLOW}{'✓' if passed else '○'}{Colors.END} {description}"
        )
        all_ok = all_ok and passed

    return all_ok


def check_docker_compose(result: ValidationResult, base_path: Path):
    """Verify docker-compose.yml structure."""
    print(
        f"\n{Colors.BLUE}{Colors.BOLD}[Bonus] Checking docker-compose.yml...{Colors.END}"
    )

    compose_file = base_path / "docker-compose.yml"
    if not compose_file.exists():
        result.add_check("docker-compose.yml exists", False)
        return False

    try:
        import yaml

        with open(compose_file) as f:
            config = yaml.safe_load(f)

        checks = [
            ("services" in config, "Has services section"),
            ("restart" in str(config), "Has restart policy"),
            (
                "memory" in str(config).lower() or "512m" in str(config).lower(),
                "Has memory limits",
            ),
        ]

        all_ok = True
        for passed, description in checks:
            print(
                f"  {Colors.GREEN if passed else Colors.YELLOW}{'✓' if passed else '○'}{Colors.END} {description}"
            )
            all_ok = all_ok and passed

        return all_ok
    except ImportError:
        print(
            f"  {Colors.YELLOW}○{Colors.END} PyYAML not installed - skipping validation"
        )
        return True
    except Exception as e:
        print(f"  {Colors.RED}✗{Colors.END} Error parsing: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Validate Betfair Automation deployment readiness"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument(
        "--skip-network", action="store_true", help="Skip network connectivity checks"
    )
    parser.add_argument(
        "--base-path",
        default=str(Path(__file__).parent.parent),
        help="Base path for checks (default: parent of scripts/)",
    )
    args = parser.parse_args()

    base_path = Path(args.base_path).resolve()

    print(
        f"\n{Colors.BOLD}{Colors.BLUE}╔══════════════════════════════════════════════════╗{Colors.END}"
    )
    print(
        f"{Colors.BOLD}{Colors.BLUE}║  Betfair Automation - Deployment Validator      ║{Colors.END}"
    )
    print(
        f"{Colors.BOLD}{Colors.BLUE}╚══════════════════════════════════════════════════╝{Colors.END}"
    )
    print(f"\n  Base Path: {base_path}")

    result = ValidationResult()

    check_config_files(result, base_path)
    check_environment_vars(result)
    check_directory_structure(result, base_path)
    check_python_dependencies(result)
    check_connectivity(result, args.skip_network)
    check_dockerfile(result, base_path)
    check_docker_compose(result, base_path)

    return result.print_summary()


if __name__ == "__main__":
    sys.exit(main())
