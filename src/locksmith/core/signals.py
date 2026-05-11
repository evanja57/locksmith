# -*- encoding: utf-8 -*-
"""
locksmith.core.signals module

Signal bridge for communication between hio Doers and Qt UI components
"""
from PySide6.QtCore import QObject, Signal
from keri import help

logger = help.ogler.getLogger(__name__)


class DoerSignalBridge(QObject):
    """
    Bridge class that allows hio Doers to emit Qt signals that UI components can connect to.

    Since Doers run in the Qt event loop via QtTask but are not QObjects themselves,
    this bridge provides a way for them to communicate with Qt widgets using signals.

    Supports dynamic signal creation: accessing any undefined attribute will automatically
    create a new Signal(dict) attribute on the class, allowing for flexible signal usage
    without pre-defining every signal type.
    """

    # General purpose signal for doer events
    # Parameters: doer_name (str), event_type (str), data (dict)
    doer_event = Signal(str, str, dict)

    # Specific signal for test doer count updates
    test_doer_count = Signal(int)

    # Witness auth dialogs emit passcodes here for the waiting UI flow
    auth_codes_entered = Signal(dict)

    def __init__(self):
        """Initialize the signal bridge."""
        super().__init__()
        logger.info("DoerSignalBridge initialized")

    def __getattr__(self, name):
        """
        Dynamically create Signal(dict) attributes when accessed.

        This allows for flexible signal creation without pre-defining every signal.
        When a non-existent attribute is accessed, a new Signal(dict) is created
        and added to the class, making it available for all instances.

        Args:
            name: Name of the attribute being accessed

        Returns:
            The requested signal attribute

        Raises:
            AttributeError: If the attribute name starts with '_' (private attributes)
        """
        # Don't intercept private attributes or Qt-specific attributes
        if name.startswith('_') or name in ('destroyed', 'objectNameChanged', 'staticMetaObject'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Create a new Signal(dict) and add it to the class
        signal = Signal(dict)
        setattr(type(self), name, signal)

        logger.debug(f"Dynamically created signal: {name}")

        # Return the signal from the instance (this will call __getattribute__ again,
        # but now the attribute exists on the class)
        return getattr(self, name)

    def emit_doer_event(self, doer_name: str, event_type: str, data: dict | None = None):
        """
        Emit a general doer event.

        Args:
            doer_name: Name of the doer emitting the event
            event_type: Type of event (e.g., 'started', 'completed', 'error')
            data: Optional dictionary with event-specific data
        """
        if data is None:
            data = {}
        logger.debug(f"Emitting doer_event: {doer_name} - {event_type} - {data}")
        self.doer_event.emit(doer_name, event_type, data)

    def emit_test_count(self, count: int):
        """
        Emit test doer count update.

        Args:
            count: Current count value from TestDoer
        """
        logger.debug(f"Emitting test_doer_count: {count}")
        self.test_doer_count.emit(count)