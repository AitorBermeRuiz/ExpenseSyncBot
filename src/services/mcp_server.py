"""MCP Server lifecycle management for .NET server."""

import atexit
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MCPServerError(Exception):
    """Exception raised for MCP server errors."""
    pass


class MCPServerManager:
    """
    Manages the lifecycle of the .NET MCP server.
    
    Ensures the server starts before operations and stops cleanly
    on script exit, even on crashes or interrupts.
    """
    
    def __init__(
        self,
        project_path: str,
        url: str = "http://localhost:5000/sse",
        startup_timeout: int = 10,
        configuration: str = "Release"
    ):
        """
        Initialize MCP Server Manager.
        
        Args:
            project_path: Path to .NET project (.csproj file or directory)
            url: URL where the server will listen
            startup_timeout: Seconds to wait for server startup
            configuration: Build configuration (Debug/Release)
        """
        self.project_path = Path(project_path)
        self.url = url
        self.startup_timeout = startup_timeout
        self.configuration = configuration
        self._process: Optional[subprocess.Popen] = None
        self._is_running = False
        
        # Validar que el proyecto existe
        if not self.project_path.exists():
            raise MCPServerError(f"Proyecto no encontrado: {self.project_path}")
        
        # Registrar handlers de limpieza
        atexit.register(self._cleanup)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        logger.info(f"⚠️ Señal recibida: {signum}")
        self.stop()
        sys.exit(0)
    
    def _cleanup(self):
        """Cleanup handler called on exit."""
        if self._is_running:
            self.stop()
    
    def start(self) -> bool:
        """
        Start the .NET MCP server.
        
        Returns:
            True if server started successfully
        
        Raises:
            MCPServerError: If server fails to start
        """
        if self._is_running:
            logger.warning("⚠️ El servidor ya está corriendo")
            return True
        
        logger.info("🚀 Iniciando servidor MCP .NET...")
        logger.info(f"   Proyecto: {self.project_path}")
        logger.info(f"   URL: {self.url}")
        
        try:
            # Construir comando
            cmd = [
                "dotnet", "run",
                "--project", str(self.project_path),
                "-c", self.configuration,
                "--no-build"  # Asume que ya está compilado
            ]
            
            # Primero intentamos sin --no-build, si falla lo intentamos con build
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env={**os.environ, "DOTNET_ENVIRONMENT": "Local"}
                )
            except Exception:
                # Si falla, intentar con build
                cmd.remove("--no-build")
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env={**os.environ, "DOTNET_ENVIRONMENT": "Local"}
                )
            
            # Esperar a que el servidor esté listo
            if not self._wait_for_startup():
                self.stop()
                raise MCPServerError("El servidor no respondió en el tiempo esperado")
            
            self._is_running = True
            logger.info("✅ Servidor MCP iniciado correctamente")
            return True
            
        except FileNotFoundError:
            raise MCPServerError(
                "dotnet no encontrado. Asegúrate de tener .NET SDK instalado."
            )
        except Exception as e:
            logger.error(f"❌ Error al iniciar servidor: {e}")
            raise MCPServerError(f"Error al iniciar servidor: {e}")
    
    def _wait_for_startup(self) -> bool:
        """Wait for server to be ready."""
        import requests
        
        logger.info(f"⏳ Esperando {self.startup_timeout}s a que el servidor inicie...")
        
        # Dar un pequeño tiempo inicial para que el proceso arranque
        time.sleep(2)
        
        start_time = time.time()
        health_url = self.url.replace("/sse", "/health")
        
        while time.time() - start_time < self.startup_timeout:
            # Verificar que el proceso sigue vivo
            if self._process and self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                logger.error(f"❌ El proceso terminó prematuramente: {stderr}")
                return False
            
            # Intentar conectar (el endpoint SSE puede no responder a GET simple)
            try:
                # Intentamos ver si el puerto está escuchando
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('localhost', 5000))
                sock.close()
                
                if result == 0:
                    logger.info("✅ Puerto 5000 disponible")
                    return True
                    
            except Exception:
                pass
            
            time.sleep(0.5)
        
        return False
    
    def stop(self) -> None:
        """Stop the MCP server gracefully."""
        if not self._process:
            return
        
        logger.info("🛑 Deteniendo servidor MCP .NET...")
        
        try:
            # Intentar terminar gracefully
            self._process.terminate()
            
            try:
                self._process.wait(timeout=5)
                logger.info("✅ Servidor detenido correctamente")
            except subprocess.TimeoutExpired:
                # Forzar cierre si no responde
                logger.warning("⚠️ Servidor no respondió, forzando cierre...")
                self._process.kill()
                self._process.wait(timeout=2)
                logger.info("✅ Servidor forzado a cerrar")
                
        except Exception as e:
            logger.error(f"❌ Error al detener servidor: {e}")
        finally:
            self._process = None
            self._is_running = False
    
    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        if not self._process:
            return False
        return self._process.poll() is None
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
