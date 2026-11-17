"""Один экземпляр приложения: разделяемая память как защёлка, сокет — только команда activate."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSharedMemory, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, key: str = "MyMusic.SingleInstance.v1", parent=None):
        super().__init__(parent)
        self.key = key
        # Qt 6.12 допускает два QLocalServer с одним именем, поэтому сокет
        # не годится как защёлка: первичность держит сегмент разделяемой памяти.
        self._shared = QSharedMemory(key + ".lock", self)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

    def acquire(self) -> bool:
        if self._shared.create(1):
            if not self._server.listen(self.key):
                QLocalServer.removeServer(self.key)
                self._server.listen(self.key)
            return True
        if self._shared.error() == QSharedMemory.SharedMemoryError.AlreadyExists:
            self._notify_primary()
            return False
        # Сегмент недоступен по другой причине: запасной путь через сокет.
        return self._server.listen(self.key)

    def _notify_primary(self) -> None:
        socket = QLocalSocket(self)
        socket.connectToServer(self.key)
        if socket.waitForConnected(500):
            socket.write(b"activate")
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            connection.readyRead.connect(lambda conn=connection: self._read(conn))
            connection.disconnected.connect(connection.deleteLater)
            if connection.bytesAvailable():
                self._read(connection)

    def _read(self, connection: QLocalSocket) -> None:
        payload = bytes(connection.readAll()).strip()
        if payload == b"activate":
            self.activated.emit()
        connection.disconnectFromServer()
