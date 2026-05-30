import logging
import threading
import time

from .docker_service import DockerService
from .state import ServiceStateManager, ServiceState
from .events import EventBus

logger = logging.getLogger(__name__)


class ServiceManager:
    """Orchestrates Docker operations and state management."""

    def __init__(self, root_dir: str, state_manager: ServiceStateManager, event_bus: EventBus):
        self.docker = DockerService(root_dir)
        self.state = state_manager
        self.events = event_bus
        self._service_tasks: dict[str, threading.Event] = {
            "redis": threading.Event(),
            "supplier": threading.Event(),
        }

    def check_and_sync_running_containers(self) -> tuple[bool, bool]:
        """Check if there are running containers and sync state.

        Returns: (has_running, has_stopped)
        """
        try:
            running = self.docker.get_running_services()
            all_services = self.docker.get_all_services()

            has_running = bool(running)
            has_stopped = bool(all_services) and not has_running

            logger.info(f"Docker check - Running: {running}, All: {all_services}")

            if "redis" in running:
                logger.info("Redis is running, syncing state")
                self._set_state("redis", ServiceState.RUNNING)

            if "supplier" in running:
                logger.info("Supplier is running, syncing state")
                self._set_state("supplier", ServiceState.RUNNING)

            return has_running, has_stopped
        except Exception as e:
            logger.error(f"Error checking containers: {str(e)}")
            return False, False

    def toggle_redis(self, active: bool):
        """Toggle Redis on/off."""
        if active:
            self.start_redis()
        else:
            self.stop_redis()

    def start_redis(self):
        """Start Redis service."""
        if self.state.is_running("redis"):
            logger.info("Redis is already running")
            return

        self._set_state("redis", ServiceState.STARTING)
        self.events.log_message.emit("# Starting Redis", "header")

        thread = threading.Thread(target=self._do_start_service, args=("redis",))
        thread.daemon = True
        thread.start()

    def stop_redis(self):
        """Stop Redis (and all dependent services)."""
        self._set_state("redis", ServiceState.STOPPING)
        self.events.log_message.emit("# Stopping Redis", "header")

        thread = threading.Thread(target=self._do_stop_service, args=("redis",))
        thread.daemon = True
        thread.start()

    def start_supplier(self):
        """Start supplier (will start Redis if needed)."""
        if self.state.is_running("supplier"):
            logger.info("Supplier is already running")
            return

        self._set_state("supplier", ServiceState.STARTING)
        self.events.log_message.emit("# Starting Supplier", "header")

        thread = threading.Thread(target=self._do_start_supplier)
        thread.daemon = True
        thread.start()

    def stop_supplier(self):
        """Stop supplier service."""
        self._set_state("supplier", ServiceState.STOPPING)
        self.events.log_message.emit("# Stopping Supplier", "header")

        thread = threading.Thread(target=self._do_stop_service, args=("supplier",))
        thread.daemon = True
        thread.start()

    def stop_all(self):
        """Stop all services."""
        self.events.log_message.emit("# Stopping all services", "header")
        self.stop_redis()

    def _do_start_service(self, service_name: str):
        """Generic service start implementation."""
        cancel_event = self._service_tasks[service_name]
        cancel_event.clear()

        try:
            self.events.log_message.emit(f"$ docker compose up -d {service_name}", "info")

            if not self.docker.start_service(service_name):
                self._set_state(service_name, ServiceState.ERROR)
                self.events.log_message.emit(f"✗ Failed to start {service_name}", "error")
                return

            if self._wait_for_health(service_name, cancel_event):
                self._set_state(service_name, ServiceState.RUNNING)
                self.events.log_message.emit(f"✓ {service_name} started", "success")
            else:
                self._set_state(service_name, ServiceState.ERROR)
                self.events.log_message.emit(f"⚠ {service_name} started but health check failed", "warning")

        except Exception as e:
            logger.error(f"Error starting {service_name}: {str(e)}")
            self._set_state(service_name, ServiceState.ERROR)
            self.events.log_message.emit(f"✗ Error: {str(e)}", "error")

    def _do_start_supplier(self):
        """Start supplier, handling Redis dependency."""
        cancel_event = self._service_tasks["supplier"]
        cancel_event.clear()

        try:
            if not self.state.is_running("redis"):
                logger.info("Redis not running, starting it first")
                self.events.log_message.emit("⚠ Redis not running, starting it first...", "info")
                self.start_redis()
                time.sleep(3)

            self.events.log_message.emit("$ docker compose up -d supplier", "info")

            if not self.docker.start_service("supplier"):
                self._set_state("supplier", ServiceState.ERROR)
                self.events.log_message.emit("✗ Failed to start supplier", "error")
                return

            if self._wait_for_health("supplier", cancel_event):
                self._set_state("supplier", ServiceState.RUNNING)
                self.events.log_message.emit("✓ supplier started", "success")
            else:
                self._set_state("supplier", ServiceState.ERROR)
                self.events.log_message.emit("⚠ supplier started but health check failed", "warning")

        except Exception as e:
            logger.error(f"Error starting supplier: {str(e)}")
            self._set_state("supplier", ServiceState.ERROR)
            self.events.log_message.emit(f"✗ Error: {str(e)}", "error")

    def _do_stop_service(self, service_name: str):
        """Generic service stop implementation."""
        try:
            logger.info(f"Starting stop_{service_name} operation")
            self.events.log_message.emit("$ docker compose down --remove-orphans -v", "info")

            if self.docker.stop_all():
                self._set_state("redis", ServiceState.STOPPED)
                self._set_state("supplier", ServiceState.STOPPED)
                self.events.log_message.emit("✓ All services stopped", "success")
            else:
                self._set_state(service_name, ServiceState.ERROR)
                self.events.log_message.emit("✗ Failed to stop services", "error")

            logger.info(f"stop_{service_name} operation completed")

        except Exception as e:
            logger.error(f"Error stopping {service_name}: {str(e)}", exc_info=True)
            self._set_state(service_name, ServiceState.ERROR)
            self.events.log_message.emit(f"✗ Error: {str(e)}", "error")

    def _wait_for_health(self, service_name: str, cancel_event: threading.Event, max_retries: int = 30) -> bool:
        """Wait for a service to be healthy, respecting cancellation."""
        logger.info(f"Starting health check for {service_name}")
        self.events.log_message.emit(f"Waiting for {service_name} to be healthy...", "info")

        for attempt in range(max_retries):
            if cancel_event.is_set():
                logger.info(f"Health check for {service_name} cancelled")
                return False

            try:
                time.sleep(0.5)

                logger.debug(f"Checking {service_name} health (attempt {attempt + 1})")
                if self.docker.check_service_health(service_name):
                    logger.info(f"{service_name} health check passed")
                    self.events.log_message.emit(f"✓ {service_name} is healthy", "success")
                    return True
            except Exception as e:
                logger.error(f"Error during health check attempt {attempt + 1}: {str(e)}", exc_info=True)

        logger.warning(f"Health check failed for {service_name} after {max_retries} attempts")
        return False

    def _set_state(self, service_name: str, state: ServiceState):
        """Update service state and emit event."""
        self.state.set_state(service_name, state)
        self.events.state_changed.emit(service_name, state.value)
