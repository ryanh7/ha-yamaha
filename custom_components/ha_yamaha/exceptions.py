#!/usr/bin/env python


class RXVException(Exception):
    pass


class DescException(RXVException):
    pass


class ResponseException(RXVException):
    """Exception raised when yamaha receiver responded with an error code."""


ReponseException = ResponseException


class MenuUnavailable(RXVException):
    """Menu control unavailable for current input."""


class MenuActionUnavailable(RXVException):
    """Menu control action unavailable for current input."""

    def __init__(self, input, action):
        super().__init__(f"{input} does not support menu cursor {action}")


class PlaybackUnavailable(RXVException):
    """Raised when playback function called on unsupported source."""

    def __init__(self, source, action):
        super().__init__(f"{source} does not support {action}")


class CommandUnavailable(RXVException):
    """Raised when command is called on unsupported device."""

    def __init__(self, zone, command):
        super().__init__(f"{zone} does not support {command}")


class UnknownPort(RXVException):
    """Raised when an unknown port is found."""

    def __init__(self, port):
        super().__init__(f"port {port} is not supported")
