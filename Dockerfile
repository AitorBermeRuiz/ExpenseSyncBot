# Usamos una imagen base ligera de Python
FROM python:3.12-slim-bookworm

# Instalamos uv (el gestor de paquetes rápido que usas)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Establecemos el directorio de trabajo
WORKDIR /app

# 1. Copiamos solo los archivos de definición de dependencias
# Esto permite a Docker cachear las librerías si no cambian
COPY pyproject.toml uv.lock ./

# 2. Instalamos las dependencias del sistema y del proyecto
# --frozen: usa exactamente las versiones del lockfile
# --no-install-project: solo instala librerías, no tu código aún
RUN uv sync --frozen --no-install-project

# 3. Copiamos el resto del código fuente
COPY . .

# 4. Instalamos el proyecto actual
RUN uv sync --frozen

# Exponemos el puerto de FastAPI
EXPOSE 8000

# Variables de entorno para optimizar Python en Docker
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Comando de arranque usando el entorno virtual creado por uv
CMD ["uv", "run", "src/main.py"]