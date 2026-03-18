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

- SSD NVMe M.2 500GB instalado en la Jetson
- PC host con Linux (Ubuntu recomendado) y conexión USB
- Cable USB-C (Jetson) a USB-A (PC host)
- Jumper o cable para cortocircuitar pines FC REC y GND (header de 14 pines)
- Cuenta gratuita de [NVIDIA Developer](https://developer.nvidia.com/)
- Acceso a internet para descargar JetPack

### Flasheo inicial vía USB al SSD NVMe (JetPack 6.2.2 / L4T R36.5)

Este método flashea el firmware y el sistema operativo directamente al SSD NVMe sin necesidad de tarjeta microSD.

#### 1. Poner la Jetson en modo Force Recovery

1. Apaga la Jetson y desconéctala de la corriente.
2. Asegúrate de que el SSD NVMe de 500 GB está instalado en la ranura M.2.
3. Localiza el header de 14 pines en la carrier board.
4. Cortocircuita los pines **FC REC** y **GND** (pines 2 y 3) con un jumper o cable.
5. Conecta el cable USB-C de la Jetson al puerto USB-A del PC host.
6. Conecta la fuente de alimentación a la Jetson para encenderla.
7. Deja el jumper conectado hasta que el flasheo comience.

#### 2. Verificar que el host detecta la Jetson

En tu PC host, ejecuta:

```bash
lsusb
```

Deberías ver un dispositivo de NVIDIA (algo como `NVIDIA Corp. APX`). Si no aparece, revisa el cable USB-C y que el jumper esté bien colocado.

#### 3. Descargar JetPack 6.2.2 (L4T R36.5)

Descarga estos dos ficheros desde la [página de Jetson Linux R36.5](https://developer.nvidia.com/embedded/jetson-linux-r365) (necesitas iniciar sesión con tu cuenta NVIDIA Developer):

1. **L4T Driver Package (BSP)** — `Jetson_Linux_R36.5.0_aarch64.tbz2`
2. **Sample Root Filesystem** — `Tegra_Linux_Sample-Root-Filesystem_R36.5.0_aarch64.tbz2`

#### 4. Preparar y flashear

En el PC host, ejecuta los siguientes comandos:

```bash
# Extraer el BSP
tar xf Jetson_Linux_R36.5.0_aarch64.tbz2

# Extraer el sistema de ficheros raíz dentro del directorio rootfs del BSP
cd Linux_for_Tegra/rootfs/
sudo tar xpf ../../Tegra_Linux_Sample-Root-Filesystem_R36.5.0_aarch64.tbz2
cd ..

# Aplicar los binarios de NVIDIA al rootfs
sudo ./apply_binaries.sh

# Instalar prerequisitos del flasheo
sudo tools/l4t_flash_prerequisites.sh

# Flashear al SSD NVMe (la Jetson debe estar en modo recovery)
sudo ./tools/kernel_flash/l4t_initrd_flash.sh \
  --external-device nvme0n1p1 \
  -p "-c ./bootloader/generic/cfg/flash_t234_qspi.xml" \
  -c ./tools/kernel_flash/flash_l4t_t234_nvme.xml \
  --showlogs --network usb0 \
  jetson-orin-nano-devkit external
```

El proceso tarda unos minutos. Al finalizar verás el mensaje:

```
Flash is successful
Reboot device
```

#### 5. Primer arranque

1. **Retira el jumper** entre los pines FC REC y GND.
2. **Desconecta el cable USB-C** del PC host.
3. **Conecta** un monitor (HDMI/DisplayPort), teclado y ratón USB.
4. **Reinicia la Jetson** — desconecta la alimentación, espera unos segundos y vuelve a conectarla.

La Jetson arrancará desde el SSD NVMe y mostrará el asistente de configuración inicial de Ubuntu (**oem-config**), donde configurarás idioma, usuario, contraseña, zona horaria, etc.

> **Si la pantalla permanece en negro** más de un par de minutos, presiona **Escape** durante el arranque para acceder al menú UEFI y verifica que el NVMe está primero en el orden de arranque.

#### 6. Verificar la instalación

Una vez dentro del escritorio, verifica que JetPack está instalado:

```bash
cat /etc/nv_tegra_release
```

E instala los componentes completos de JetPack (CUDA, cuDNN, TensorRT, etc.):

```bash
sudo apt update
sudo apt install nvidia-jetpack
```

### Activar modo MAXN SUPER

Para obtener el máximo rendimiento:

1. Haz clic en el icono de NVIDIA en la barra superior de Ubuntu
2. Selecciona **Power Mode**
3. Elige **MAXN SUPER** para habilitar el rendimiento máximo

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
