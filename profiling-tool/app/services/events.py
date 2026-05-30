from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Pub/Sub event bus for the application.

    Qt AutoConnection ensures that signals emitted from background threads
    are safely queued on the main thread, fixing thread-safety issues
    with widget modifications.
    """

    log_message = Signal(str, str)  # (message, level)
    state_changed = Signal(str, str)  # (service_name, state_value)
