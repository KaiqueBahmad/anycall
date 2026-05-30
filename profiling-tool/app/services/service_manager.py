import logging
import threading
import time

from .docker_service import DockerService
from .state import ServiceStateManager, ServiceState

logger = logging.getLogger(__name__)


class ServiceManager:
    """Orchestrates Docker operations and state management."""

    def __init__(self, root_dir: str, state_manager: ServiceStateManager):
        self.docker = DockerService(root_dir)
        self.state = state_manager
        self._health_check_timer = None

    def toggle_redis(self, active: bool, on_log_msg=None):
        """Toggle Redis on/off."""
        if active:
            self.start_redis(on_log_msg)
        else:
            self.stop_redis(on_log_msg)

    def start_redis(self, on_log_msg=None):
        """Start Redis service."""
        if self.state.is_running("redis"):
            logger.info("Redis is already running")
            return

        self.state.set_state("redis", ServiceState.STARTING)
        if on_log_msg:
            on_log_msg("# Starting Redis", "header")

        thread = threading.Thread(target=self._do_start_redis, args=(on_log_msg,))
        thread.daemon = True
        thread.start()

    def stop_redis(self, on_log_msg=None):
        """Stop Redis (and all dependent services)."""
        self.state.set_state("redis", ServiceState.STOPPING)
        if on_log_msg:
            on_log_msg("# Stopping Redis", "header")

        thread = threading.Thread(target=self._do_stop_redis, args=(on_log_msg,))
        thread.daemon = True
        thread.start()

    def start_supplier(self, on_log_msg=None):
        """Start supplier (will start Redis if needed)."""
        # Check if Redis is running
        if not self.state.is_running("redis"):
            logger.info("Redis not running, starting it first")
            if on_log_msg:
                on_log_msg("⚠ Redis not running, starting it first...", "info")
            self.start_redis(on_log_msg)
            # Wait a bit for redis to start
            time.sleep(3)

        self.state.set_state("supplier", ServiceState.STARTING)
        if on_log_msg:
            on_log_msg("# Starting Supplier", "header")

        thread = threading.Thread(target=self._do_start_supplier, args=(on_log_msg,))
        thread.daemon = True
        thread.start()

    def stop_supplier(self, on_log_msg=None):
        """Stop supplier service."""
        self.state.set_state("supplier", ServiceState.STOPPING)
        if on_log_msg:
            on_log_msg("# Stopping Supplier", "header")

        thread = threading.Thread(target=self._do_stop_supplier, args=(on_log_msg,))
        thread.daemon = True
        thread.start()

    def _do_start_redis(self, on_log_msg=None):
        """Actually start Redis."""
        try:
            if on_log_msg:
                on_log_msg("$ docker compose up -d redis", "info")

            if not self.docker.start_redis():
                self.state.set_state("redis", ServiceState.ERROR, "Failed to start Redis")
                if on_log_msg:
                    on_log_msg("✗ Failed to start Redis", "error")
                return

            # Wait for health check
            if self._wait_for_health("redis", on_log_msg):
                self.state.set_state("redis", ServiceState.RUNNING)
                if on_log_msg:
                    on_log_msg("✓ Redis started", "success")
            else:
                self.state.set_state("redis", ServiceState.ERROR, "Health check failed")
                if on_log_msg:
                    on_log_msg("⚠ Redis started but health check failed", "warning")

        except Exception as e:
            logger.error(f"Error starting Redis: {str(e)}")
            self.state.set_state("redis", ServiceState.ERROR, str(e))
            if on_log_msg:
                on_log_msg(f"✗ Error: {str(e)}", "error")

    def _do_stop_redis(self, on_log_msg=None):
        """Actually stop Redis."""
        try:
            logger.info("Starting stop_redis operation")

            if on_log_msg:
                try:
                    on_log_msg("$ docker compose down --remove-orphans -v", "info")
                except Exception as e:
                    logger.error(f"Error calling on_log_msg: {str(e)}")

            logger.info("Calling docker.stop_all()")
            result = self.docker.stop_all()
            logger.info(f"docker.stop_all() returned: {result}")

            if result:
                logger.info("Setting redis state to STOPPED")
                self.state.set_state("redis", ServiceState.STOPPED)
                logger.info("Setting supplier state to STOPPED")
                self.state.set_state("supplier", ServiceState.STOPPED)
                logger.info("Both states set")
                if on_log_msg:
                    try:
                        on_log_msg("✓ All services stopped", "success")
                    except Exception as e:
                        logger.error(f"Error in success log: {str(e)}")
            else:
                self.state.set_state("redis", ServiceState.ERROR, "Failed to stop")
                if on_log_msg:
                    try:
                        on_log_msg("✗ Failed to stop services", "error")
                    except Exception as e:
                        logger.error(f"Error in failure log: {str(e)}")

            logger.info("stop_redis operation completed")

        except Exception as e:
            logger.error(f"Error stopping Redis: {str(e)}", exc_info=True)
            self.state.set_state("redis", ServiceState.ERROR, str(e))
            if on_log_msg:
                try:
                    on_log_msg(f"✗ Error: {str(e)}", "error")
                except Exception as log_e:
                    logger.error(f"Error logging exception: {str(log_e)}")

    def _do_start_supplier(self, on_log_msg=None):
        """Actually start Supplier."""
        try:
            if on_log_msg:
                on_log_msg("$ docker compose up -d supplier", "info")

            if not self.docker.start_supplier():
                self.state.set_state("supplier", ServiceState.ERROR, "Failed to start supplier")
                if on_log_msg:
                    on_log_msg("✗ Failed to start supplier", "error")
                return

            # Wait for health check
            if self._wait_for_health("supplier", on_log_msg):
                self.state.set_state("supplier", ServiceState.RUNNING)
                if on_log_msg:
                    on_log_msg("✓ Supplier started", "success")
            else:
                self.state.set_state("supplier", ServiceState.ERROR, "Health check failed")
                if on_log_msg:
                    on_log_msg("⚠ Supplier started but health check failed", "warning")

        except Exception as e:
            logger.error(f"Error starting supplier: {str(e)}")
            self.state.set_state("supplier", ServiceState.ERROR, str(e))
            if on_log_msg:
                on_log_msg(f"✗ Error: {str(e)}", "error")

    def _do_stop_supplier(self, on_log_msg=None):
        """Actually stop Supplier."""
        try:
            # Just stop supplier, keep redis running
            if on_log_msg:
                on_log_msg("$ docker compose down supplier", "info")

            # For now, we stop all. Later can be more granular
            if self.docker.stop_all():
                self.state.set_state("supplier", ServiceState.STOPPED)
                self.state.set_state("redis", ServiceState.STOPPED)
                if on_log_msg:
                    on_log_msg("✓ Services stopped", "success")
            else:
                self.state.set_state("supplier", ServiceState.ERROR, "Failed to stop")
                if on_log_msg:
                    on_log_msg("✗ Failed to stop services", "error")

        except Exception as e:
            logger.error(f"Error stopping supplier: {str(e)}")
            self.state.set_state("supplier", ServiceState.ERROR, str(e))
            if on_log_msg:
                on_log_msg(f"✗ Error: {str(e)}", "error")

    def _wait_for_health(self, service_name: str, on_log_msg=None, max_retries: int = 30) -> bool:
        """Wait for a service to be healthy."""
        logger.info(f"Starting health check for {service_name}")

        if on_log_msg:
            try:
                on_log_msg(f"Waiting for {service_name} to be healthy...", "info")
            except Exception as e:
                logger.error(f"Error in on_log_msg: {str(e)}")

        for attempt in range(max_retries):
            try:
                time.sleep(0.5)

                if service_name == "redis":
                    logger.debug(f"Checking redis health (attempt {attempt + 1})")
                    if self.docker.check_redis_health():
                        logger.info(f"Redis health check passed")
                        if on_log_msg:
                            try:
                                on_log_msg(f"✓ {service_name} is healthy", "success")
                            except Exception as e:
                                logger.error(f"Error in success callback: {str(e)}")
                        return True

                elif service_name == "supplier":
                    logger.debug(f"Checking supplier health (attempt {attempt + 1})")
                    if self.docker.check_supplier_health():
                        logger.info(f"Supplier health check passed")
                        if on_log_msg:
                            try:
                                on_log_msg(f"✓ {service_name} is healthy", "success")
                            except Exception as e:
                                logger.error(f"Error in success callback: {str(e)}")
                        return True
            except Exception as e:
                logger.error(f"Error during health check attempt {attempt + 1}: {str(e)}", exc_info=True)

        logger.warning(f"Health check failed for {service_name} after {max_retries} attempts")
        return False
