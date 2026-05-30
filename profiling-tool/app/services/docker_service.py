import subprocess
import logging
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ServiceType(Enum):
    REDIS = "redis"
    SUPPLIER = "supplier"


@dataclass
class ServiceStatus:
    name: str
    healthy: bool
    last_check: float = 0


class DockerService:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self._statuses: dict[str, ServiceStatus] = {}

    def start_redis(self) -> bool:
        """Start Redis service."""
        return self._run_compose("up", "-d", "--remove-orphans", "redis")

    def start_supplier(self) -> bool:
        """Start supplier service (requires redis to be running)."""
        return self._run_compose("up", "-d", "--remove-orphans", "supplier")

    def stop_all(self) -> bool:
        """Stop all services."""
        return self._run_compose("down", "--remove-orphans", "-v")

    def stop_redis(self) -> bool:
        """Stop only redis (this will also stop dependent services)."""
        return self._run_compose("down", "--remove-orphans", "-v")

    def check_redis_health(self) -> bool:
        """Check if Redis is healthy."""
        try:
            logger.debug("Checking redis health with redis-cli ping")
            result = self._exec_in_container("redis", ["redis-cli", "ping"])
            logger.debug(f"Redis health check result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error checking redis health: {str(e)}", exc_info=True)
            return False

    def check_supplier_health(self) -> bool:
        """Check if Supplier is healthy."""
        try:
            logger.debug("Checking supplier health with curl")
            result = self._exec_in_container("supplier", ["curl", "-f", "http://localhost:8080/health"])
            logger.debug(f"Supplier health check result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error checking supplier health: {str(e)}", exc_info=True)
            return False

    def get_running_services(self) -> set[str]:
        """Get list of currently running services."""
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--services", "--filter", "status=running"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return set(s.strip() for s in result.stdout.strip().split("\n") if s.strip())
            return set()
        except Exception as e:
            logger.error(f"Error getting running services: {str(e)}")
            return set()

    def get_all_services(self) -> set[str]:
        """Get list of all services (running or stopped)."""
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--services"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return set(s.strip() for s in result.stdout.strip().split("\n") if s.strip())
            return set()
        except Exception as e:
            logger.error(f"Error getting all services: {str(e)}")
            return set()

    def _run_compose(self, *args) -> bool:
        """Run a docker compose command."""
        try:
            cmd = ["docker", "compose"] + list(args)
            logger.info(f"Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )

            logger.info(f"Command returned: {result.returncode}")
            if result.stdout:
                logger.debug(f"stdout: {result.stdout}")
            if result.stderr:
                logger.debug(f"stderr: {result.stderr}")

            if result.returncode == 0:
                logger.info(f"Command succeeded")
                return True
            else:
                error_output = result.stderr or result.stdout
                logger.error(f"Command failed: {error_output}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Command timeout")
            return False
        except Exception as e:
            logger.error(f"Command error: {str(e)}", exc_info=True)
            return False

    def _exec_in_container(self, service: str, cmd: list[str]) -> bool:
        """Execute a command inside a container."""
        try:
            full_cmd = ["docker", "compose", "exec", "-T", service] + cmd
            result = subprocess.run(
                full_cmd,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=3,
            )
            return result.returncode == 0
        except Exception:
            return False
