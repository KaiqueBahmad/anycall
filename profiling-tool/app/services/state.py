import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ServiceState(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class Service:
    name: str
    state: ServiceState = ServiceState.STOPPED
    last_error: str = ""

    def is_running(self) -> bool:
        return self.state == ServiceState.RUNNING

    def is_loading(self) -> bool:
        return self.state in (ServiceState.STARTING, ServiceState.STOPPING)


class ServiceStateManager:
    """Central state management for all services."""

    def __init__(self):
        self._services: dict[str, Service] = {
            "redis": Service("redis"),
            "supplier": Service("supplier"),
        }
        self._listeners: list = []

    def register_listener(self, callback):
        """Register a callback that's called when state changes."""
        self._listeners.append(callback)

    def _notify_listeners(self):
        """Notify all listeners of state change."""
        for callback in self._listeners:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in state listener: {str(e)}")

    def set_state(self, service_name: str, state: ServiceState, error: str = ""):
        """Update service state."""
        logger.debug(f"set_state called with service={service_name}, state={state.value}")

        if service_name not in self._services:
            logger.warning(f"Unknown service: {service_name}")
            return

        service = self._services[service_name]
        service.state = state
        service.last_error = error

        logger.info(f"Service {service_name} state changed to {state.value}")
        logger.debug(f"About to notify {len(self._listeners)} listeners")

        try:
            self._notify_listeners()
            logger.debug(f"Listeners notified successfully")
        except Exception as e:
            logger.error(f"Error notifying listeners: {str(e)}", exc_info=True)
            raise

    def get_state(self, service_name: str) -> ServiceState:
        """Get current state of a service."""
        if service_name not in self._services:
            return ServiceState.STOPPED
        return self._services[service_name].state

    def is_running(self, service_name: str) -> bool:
        """Check if service is running."""
        return self.get_state(service_name) == ServiceState.RUNNING

    def get_all_services(self) -> dict[str, Service]:
        """Get all services."""
        return self._services.copy()
