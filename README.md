# StoryBot: Robot Cuentacuentos

**StoryBot** es un robot narrador de cuentos para niños de 3 a 6 años que funciona 100% sin conexión a internet. Ejecuta modelos de IA localmente en una placa NVIDIA Jetson Orin Nano Super 8GB.

## Características

- **Cuentos narrados**: Toca una tarjeta NFC y el robot reproduce el cuento en audio
- **Cuentos interactivos**: Los niños eligen el camino de la historia
- **Cuentos inventados por IA**: Generación automática de cuentos con modelos locales
- **Impresión de pegatinas**: Imprime dibujos para colorear en Brother QL-800
- **Panel de administración**: Gestión de contenidos desde móvil (WiFi local)

## Hardware Requerido

| Componente | Descripción |
|------------|-------------|
| NVIDIA Jetson Orin Nano Super 8GB | Unidad de procesamiento principal |
| SSD NVMe M.2 (recomendado) | Almacenamiento rápido para modelos de IA |
| Lector NFC USB ACR122U | Lectura de tarjetas NFC |
| Tarjetas NFC NTAG213 | Identificación de cuentos |
| Pantalla táctil 7" HDMI | Interfaz para niños |
| Impresora Brother QL-800 | Impresión de pegatinas |
| Router TP-Link TL-WR802N | Red WiFi local para docentes |
| Tira LED RGB | Iluminación ambiental |

## Configuración del Jetson Orin Nano

### Requisitos previos

- Tarjeta microSD de al menos 64GB (UHS-1 recomendado)
- Equipo con Ubuntu (para actualizar firmware) o lector de tarjetas SD
- Acceso a internet para descargar JetPack

### Actualización del firmware

El Jetson Orin Nano Developer Kit viene con un firmware antiguo de fábrica que **no es compatible** con JetPack 6.x. Debes actualizar al firmware más reciente antes de usar la tarjeta SD con JetPack 6.x.

#### Opción 1: Actualizar firmware desde otra Jetson (recomendado)

1. Descarga la imagen de JetPack 5.1.3 desde la [página de JetPack](https://developer.nvidia.com/embedded/jetpack)
2. Flashea la imagen en una tarjeta microSD usando [Etcher](https://etcher.balena.io/)
3. Inserta la tarjeta SD en la ranura del Jetson
4. Enciende el Jetson y espera a que arranque
5. Descarga el script de actualización desde https://www.jetson-ai-lab.com/initial_setup_jon.html
6. Ejecuta el script para actualizar el firmware a la versión compatible con JetPack 6.x

#### Opción 2: Actualizar firmware con NVIDIA SDK Manager

1. Descarga e instala [NVIDIA SDK Manager](https://developer.nvidia.com/nvidia-sdk-manager) en un PC con Ubuntu
2. Conecta el Jetson al PC mediante USB-C en modo recuperación
3. Ejecuta SDK Manager y selecciona JetPack 6.x
4. Flashea el firmware actualizado

### Instalar JetPack 6.x

1. Descarga la imagen de JetPack 6.x desde la [página oficial de NVIDIA](https://developer.nvidia.com/embedded/jetpack)
2. Formatea la tarjeta microSD usando [SD Memory Card Formatter](https://www.sdcard.org/downloads/formatter_4/)
3. Escribe la imagen en la tarjeta microSD usando [Etcher](https://etcher.balena.io/)
4. Inserta la tarjeta microSD en la ranura del Jetson
5. Enciende el Jetson

### Configuración inicial

1. Conecta el teclado, ratón y monitor
2. Enciende el Jetson con la fuente de alimentación incluida
3. Sigue los pasos del asistente de configuración:
   - Acepta los términos de NVIDIA
   - Selecciona idioma, teclado y zona horaria
   - Crea usuario y contraseña
4. Conecta a la red WiFi o Ethernet

### Activar modo MAXN SUPER

Para obtener el máximo rendimiento:

1. Haz clic en el icono de NVIDIA en la barra superior de Ubuntu
2. Selecciona **Power Mode**
3. Elige **MAXN SUPER** para habilitar el rendimiento máximo

### Instalar SSD NVMe (recomendado)

Para mejorar los tiempos de carga de modelos de IA:

1. Apaga el Jetson y desconecta la alimentación
2. Instala el SSD NVMe M.2 en la ranura correspondiente
3. Enciende el Jetson
4. Configura el SSD como dispositivo de arranque principal

Consulta la [guía oficial de NVIDIA](https://developer.nvidia.com/embedded/learn/get-started-jetson-orin-nano-devkit) para instrucciones detalladas.

## Modelo de IA

- **LLM**: Qwen 2.5 3B Instruct via Ollama (~2GB RAM)
- **TTS**: Piper TTS con voces en español (~400MB RAM)
- **Imágenes**: Stable Diffusion 1.5 + LCM LoRA (~2.8GB RAM)

## Arquitectura de Software

```
┌─────────────────────────────────────────┐
│  Dispositivos externos (WiFi local)    │
│  Móvil/portátil docente → /admin        │
└────────────────┬────────────────────────┘
                 │ HTTP/SSE
┌────────────────▼────────────────────────┐
│         FASTAPI (puerto 8000)           │
│  /        → Interfaz niños (kiosk)     │
│  /admin   → Panel docentes             │
│  /api/*   → Endpoints REST + SSE       │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│         Gestor de Modelos             │
│  Ollama (LLM) │ Piper TTS │ SD 1.5    │
└────────────────┬────────────────────────┘
                 │
┌────────────────▼────────────────────────┐
│         Capa de Hardware              │
│  NFC │ Brother QL │ LEDs │ Audio       │
└────────────────────────────────────────┘
```

## Installation

### Requisitos previos

- Python 3.10+
- uv (gestor de paquetes)
- JetPack 6.2.1 instalado

### Dependencias del sistema (JetPack 6.2.1)

JetPack 6.2.1 incluye las siguientes librerías CUDA 12.6.10 que se instalan vía apt:

```bash
# Instalar JetPack completo (incluye todas las librerías CUDA)
sudo apt update
sudo apt install nvidia-jetpack

# O instalar librerías específicas manualmente:
sudo apt install \
    libcudnn9 \
    libcudnn9-dev \
    libcudnn9-static \
    libcusolver-12-6 \
    libcusparse-12-6 \
    libcurand-12-6 \
    libcufft-12-6 \
    libcublas-12-6 \
    libnvjpeg-12-6 \
    libnvjitlink-12-6
```

**Componentes incluidos en JetPack 6.2.1:**

| Componente | Versión |
|------------|---------|
| CUDA | 12.6.10 |
| TensorRT | 10.3.0 |
| cuDNN | 9.3.0 |
| VPI | 3.2 |
| DLA | 3.14 |
| DeepStream | 7.1 |
| OpenCV | 4.8.0 |
| Vulkan | 1.3 |
| OpenGL | 4.6 |
| OpenGLES | 3.2 |

### Configuración del entorno

```bash
# Crear entorno virtual
uv venv
uv sync

# Instalar dependencias de desarrollo
uv sync --extra dev

# Instalar dependencias de IA para Jetson (opcional)
uv sync --extra jetson
```

### Despliegue en Jetson

Para desplegar StoryBot en un Jetson Orin Nano Super:

```bash
# Clonar el repositorio
git clone <repo-url> /home/ari/storybot
cd /home/ari/storybot

# Ejecutar el script de instalación
sudo bash deploy/install.sh
```

El script de instalación realiza:
- Crea entorno virtual Python con uv e instala dependencias
- Descarga modelos Piper TTS (voz española)
- Configura servicio systemd para FastAPI (`storybot.service`)
- Instala Nginx como proxy inverso (puerto 80 -> 8000)
- Configura autologin GDM3 para usuario `ari`
- Crea autostart GNOME para Firefox en modo kiosk
- Imprime instrucciones para configurar el AP WiFi TP-Link

Para iniciar manualmente después de la instalación:

```bash
sudo systemctl start storybot
```

### Configuración

Crea un archivo `.env` con las variables de configuración necesarias.

## Uso

### Ejecutar el servidor de desarrollo

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Interfaz de niños

Accede desde la pantalla táctil del robot: `http://localhost/`

### Panel de administración

Accede desde un dispositivo móvil conectado a la red WiFi: `http://192.168.12.1/admin`

## Pruebas

```bash
# Ejecutar todas las pruebas
uv run pytest

# Ejecutar con cobertura
uv run pytest --cov=app --cov-report=html
```

## Estándares de Código

### Formateo

```bash
uv run black .
```

### Linting

```bash
uv run ruff check . --fix
uv run ruff format .
```

## Endpoints API

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/stories` | GET | Listar todos los cuentos |
| `/api/stories` | POST | Subir nuevo cuento |
| `/api/stories/{id}` | GET | Obtener cuento por ID |
| `/api/stories/{id}` | DELETE | Eliminar cuento |
| `/api/generate/story` | POST | Generar cuento con IA (SSE) |
| `/api/generate/status/{task_id}` | GET | Progreso de generación (SSE) |
| `/api/nfc/read` | GET | Leer tarjeta NFC (SSE) |
| `/api/nfc/write` | POST | Escribir UID en tarjeta NFC |
| `/api/printer/print` | POST | Imprimir pegatina |
| `/api/system/status` | GET | Estado del sistema |
| `/api/system/led` | POST | Controlar LEDs RGB |

## Desarrollo

### Estructura del proyecto

```
storybot/
├── app/
│   ├── main.py              # Punto de entrada FastAPI
│   ├── config.py            # Configuración
│   ├── routers/             # Endpoints API
│   │   ├── stories.py       # CRUD de cuentos
│   │   ├── admin.py         # Panel admin
│   │   ├── generate.py      # Generación IA
│   │   ├── nfc.py           # Manejo NFC
│   │   ├── printer.py       # Impresora
│   │   └── system.py        # Estado y LEDs
│   ├── services/            # Lógica de negocio
│   │   ├── model_manager.py # Carga de modelos
│   │   ├── story_generator.py
│   │   ├── tts_engine.py
│   │   ├── image_generator.py
│   │   ├── nfc_handler.py
│   │   ├── printer_handler.py
│   │   ├── led_controller.py
│   │   ├── audio_player.py
│   │   └── content_manager.py
│   └── models/              # Esquemas Pydantic
├── static/
│   ├── children/            # Interfaz niños
│   └── admin/               # Panel docentes
├── content/                 # Contenido almacenado
│   ├── stories/
│   ├── interactive/
│   └── images/
└── tests/                   # Suite de pruebas
```

## Licencia

MIT License - ver archivo LICENSE

## Presupuesto

Ver documento `docs/plan_robot_cuentacuentos.md` para el presupuesto completo de hardware.
