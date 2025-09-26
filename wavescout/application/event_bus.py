"""Type-safe publish-subscribe event bus for the application layer."""

from typing import TypeVar, Callable, Type
import logging
from collections import defaultdict

from wavescout.application.events import Event

T = TypeVar('T', bound=Event)


class EventBus:
    """Type-safe publish-subscribe event bus."""
    
    def __init__(self) -> None:
        self._subscribers: dict[Type[Event], list[Callable[[Event], None]]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)
    
    def subscribe(self, event_type: Type[T], handler: Callable[[T], None]) -> None:
        """Subscribe to events of specific type."""
        print(f"[EVENT_BUS] Subscribing {handler.__name__ if hasattr(handler, '__name__') else handler} to {event_type.__name__}")
        # Cast is safe because we ensure type consistency
        self._subscribers[event_type].append(handler)  # type: ignore[arg-type]
        print(f"[EVENT_BUS] Now {len(self._subscribers[event_type])} subscribers for {event_type.__name__}")
    
    def unsubscribe(self, event_type: Type[T], handler: Callable[[T], None]) -> None:
        """Unsubscribe from events."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)  # type: ignore[arg-type]
            except ValueError:
                pass
                
    def publish(self, event: Event) -> None:
        """Publish event to all subscribers."""
        import threading
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])

        print(f"[EVENT_BUS] Publishing {event_type.__name__} on thread {threading.current_thread().name}")
        print(f"[EVENT_BUS] Found {len(handlers)} subscribers")

        for handler in handlers:
            try:
                handler_name = handler.__name__ if hasattr(handler, '__name__') else str(handler)
                print(f"[EVENT_BUS] Calling handler {handler_name}")
                handler(event)
                print(f"[EVENT_BUS] Handler {handler_name} completed")
            except Exception as e:
                print(f"[EVENT_BUS] Handler {handler_name} raised exception: {e}")
                self._logger.error(f"Handler error for {event_type.__name__}: {e}")
                if __debug__:
                    raise
    
    def clear(self) -> None:
        """Clear all subscriptions."""
        self._subscribers.clear()
    
    def clear_event_type(self, event_type: Type[Event]) -> None:
        """Clear all subscriptions for a specific event type."""
        self._subscribers.pop(event_type, None)