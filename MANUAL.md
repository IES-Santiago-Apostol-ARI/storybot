# Manual de Usuario — StoryBot

## ¿Qué es StoryBot?

StoryBot es un robot de cuentos para niños de 3 a 6 años. Cuenta historias grabadas y puede crear nuevas historias de forma automática usando inteligencia artificial, todo sin necesidad de conexión a internet.

---

## Encender y apagar

### Encender

Conecta la alimentación del robot. Al arrancar:

- La tira LED hace un barrido de luz de izquierda a derecha (señal de arranque).
- La pantalla táctil abre sola la pantalla principal de los niños.

El arranque completo tarda alrededor de un minuto. Mientras tanto, la pantalla puede quedarse en negro o mostrar un mensaje de error del navegador: es normal, se recarga sola.

### Apagar

Pulsa el **botón de apagado** (ver "Botones físicos del robot"). Espera a que la pantalla se apague y las luces se queden fijas antes de desconectar la alimentación.

**Importante**: no desconectes el robot de la corriente sin apagarlo antes; podrías dañar los datos guardados.

---

## Para Niños — Modo Juego

### Pantalla principal

Al encender StoryBot, verás la pantalla principal con grandes iconos (emojis) flotando. Cada icono representa un cuento diferente.

- **Para escuchar un cuento**: Toca el icono del cuento que quieras escuchar.
- **Si no hay cuentos**: Verás un robot durmiendo. Eso significa que aún no se han añadido cuentos.

### Escuchando un cuento

Cuando empiezas a escuchar un cuento:

- En el centro verás una imagen grande o el emoji del cuento.
- Un pequeño robot caminará de izquierda a derecha mientras se cuenta la historia.
- Las luces LED cambiarán al color del cuento.

### Pausar y reanudar

- **Para pausar**: Toca cualquier parte de la pantalla en el centro. Aparecerá un icono de pausa grande.
- **Para reanudar**: Toca de nuevo la pantalla. El cuento seguirá desde donde se quedó.

### Cuando termina el cuento

Cuando el cuento termina, verás una pantalla de celebración con confeti (🎉) y estrellas. Después de unos segundos, volverás automáticamente a la pantalla principal.

### Tarjetas mágicas NFC

StoryBot puede reconocer tarjetas especiales que se acercan al robot.

- **Tarjetas de cuentos**: Acerca una tarjeta al robot para empezar a escuchar el cuento asociado. Si acercas la misma tarjeta mientras el cuento suena, se pausará o reanudará.
- **Tarjetas de parámetros**: Estas tarjetas añaden ideas para crear un cuento nuevo. Verás aparecer pequeños iconos en la parte superior de la pantalla con cada tarjeta que tocas (por ejemplo: "🐉 Dragón", "🏰 Castillo").
- **Tarjeta Go**: Cuando hayas tocado varias tarjetas de parámetros, toca la tarjeta Go para que StoryBot cree un cuento nuevo con esas ideas. Verás un robot pensando (🤖) con las ideas elegidas mientras prepara la historia. El cuento empieza a escucharse en cuanto está lista la primera parte, sin esperar al final; el dibujo de portada llega después, al terminar.
- **Si tardas demasiado**: las ideas acumuladas se olvidan pasados unos **30 segundos** sin tocar ninguna tarjeta. Si eso pasa, vuelve a tocar las tarjetas de parámetros antes de la tarjeta Go.
- **Tarjeta Go sin ideas**: si tocas Go sin haber elegido ningún parámetro, solo verás la pantalla del robot pensando un momento y volverás al inicio.
- **Sin IA**: en un robot sin inteligencia artificial disponible (ver "Modo" en el panel), las tarjetas de parámetros y la tarjeta Go no crean nada; solo suena un pequeño toque.

### Tarjetas que el robot no conoce

Si acercas una tarjeta que no está registrada, el robot borra los parámetros que se hubieran acumulado y vuelve a la pantalla principal. No pasa nada más: basta con registrar esa tarjeta desde el panel de administración si quieres usarla.

---

## Botones físicos del robot

El robot tiene **cuatro botones** en la carcasa. Funcionan siempre, aunque la pantalla esté bloqueada o el navegador se haya quedado colgado, porque los gestiona directamente el robot y no la pantalla.

| Botón | Qué hace |
|-------|----------|
| **Apagado** | Apaga el robot de forma segura. |
| **Parar** | Detiene el cuento al instante y vuelve a la pantalla principal. |
| **Dibujo** | Crea un dibujo para colorear a partir del cuento que está sonando. |
| **Luces** | Lanza una animación arcoíris en la tira LED. |

### Botón de apagado

Apaga el robot (equivale a un apagado ordenado del sistema). Espera a que la pantalla se apague antes de desconectar la alimentación. Para volver a encenderlo hay que quitar y volver a dar corriente.

### Botón de parar

Corta el audio inmediatamente y devuelve la pantalla a la página principal, esté sonando un cuento grabado o uno generado por la IA. Es el botón que conviene tener a mano en clase.

### Botón de dibujo

Mientras suena un cuento de la biblioteca, este botón pide a la IA un **dibujo en blanco y negro, con líneas gruesas, pensado para colorear**. El dibujo se basa en las ideas con las que se creó el cuento (si es un cuento generado por la IA) o, si es un cuento subido por el profesor, en su título.

- El dibujo tarda alrededor de **un minuto o dos** en aparecer; mientras tanto el cuento sigue sonando con normalidad.
- Cuando está listo, la tira LED hace un **arcoíris** y el dibujo aparece en la pantalla (salvo que el cuento ya tenga su propia portada: en ese caso la portada original se mantiene en pantalla y el dibujo se guarda igualmente para imprimirlo).
- Si vuelves a pulsar el botón mientras se está creando un dibujo, la pulsación se ignora. Espera al arcoíris.
- Si lo pulsas otra vez cuando ya ha terminado, se genera un **dibujo nuevo distinto** que sustituye al anterior de ese cuento.
- Si **no hay ningún cuento sonando**, o el robot no tiene IA disponible, la tira LED parpadea en **ámbar** y no ocurre nada más.
- Los dibujos generados se pueden imprimir después desde el panel de administración, en la sección "Historias generadas".

### Botón de luces

Lanza una animación arcoíris en la tira LED durante un segundo y medio. No afecta al cuento que esté sonando; es puramente decorativo y sirve también para comprobar que la tira funciona.

### Si un botón no responde

- Vuelve a pulsarlo con un toque firme y corto: pulsaciones muy seguidas (menos de medio segundo) se ignoran a propósito para evitar repeticiones.
- El botón de dibujo es el único que puede parecer "no hacer nada": comprueba si la tira LED ha parpadeado en ámbar (no hay cuento sonando o no hay IA).

---

## Qué significan las luces

La tira LED acompaña lo que está pasando. Estos son los estados:

| Luz | Significado |
|-----|-------------|
| Barrido de izquierda a derecha | El robot está arrancando. |
| Brillo cálido tenue y estable | En reposo, esperando una tarjeta o un toque. |
| Color del cuento, subiendo y bajando suavemente | Cuento sonando (cada cuento tiene su color configurado). |
| Mismo color, congelado sin latir | Cuento en pausa. |
| Destello blanco corto | Se ha leído una tarjeta de cuento. |
| Se enciende una luz más por cada toque | Se ha añadido una tarjeta de parámetro. |
| Destello verde largo | Se ha leído la tarjeta Go: empieza a crear el cuento. |
| Luz que recorre la tira | El robot está pensando o generando. |
| Ámbar unos segundos y se apaga | Aviso o error (por ejemplo, botón de dibujo sin cuento sonando). |
| Arcoíris | Dibujo listo, o botón de luces pulsado. |

---

## Para Profesores — Panel de Administración

El panel de administración se abre desde un navegador:

- **Desde un móvil o tablet**: conéctate a la red WiFi del robot (**StoryBot**) y abre `http://192.168.12.1/admin`.
- **Desde la pantalla táctil del robot**: `http://localhost/admin`.

El panel no pide usuario ni contraseña: la protección es la propia red del robot, así que **no conectes StoryBot a una red WiFi abierta o compartida** si no quieres que otras personas puedan entrar al panel.

### Vista general

En la parte superior verás:

- **Modo**: Indica si la inteligencia artificial está disponible ("Modo: Completo") o no ("Modo: Básico (sin IA)").
- **Iconos de estado** (a la derecha):
  - **Lector NFC**: Verde = conectado, Rojo = error, Pulsando = comprobando.
  - **Tira LED**: Verde = funcionando, Rojo = error.
  - **WiFi**: Muestra la red a la que está conectado. Toca para ir a la configuración de WiFi.
  - **Bluetooth**: Muestra el altavoz conectado. Toca para ir a la configuración de Bluetooth.
  - **Actualización**: Aparece con un punto rojo cuando hay una nueva versión disponible.

---

### Subir un cuento

1. En la sección "Subir Historia", rellena los campos:
   - **Título**: Nombre del cuento (obligatorio, máximo 100 caracteres).
   - **Emoji**: El icono que representará el cuento. Pulsa el botón de emojis para elegir.
   - **Color LED**: El color de las luces mientras se cuenta este cuento.
   - **Archivo de Audio**: Sube el archivo de audio del cuento (MP3 o WAV).
   - **Imagen de Portada** (opcional): Sube una imagen para que aparezca en pantalla.
2. Pulsa **Subir Historia**.

### Editar un cuento

1. En la sección "Biblioteca de Cuentos", localiza el cuento y pulsa **Editar**.
2. El formulario se rellenará con los datos actuales.
3. Modifica lo que necesites. Si no subes un nuevo audio, se mantendrá el actual.
4. Pulsa **Guardar Cambios**.
5. Para cancelar, pulsa **Cancelar** (se pedirá confirmación si hay cambios sin guardar).

### Eliminar un cuento

1. En la sección "Biblioteca de Cuentos", localiza el cuento.
2. Pulsa **Eliminar**.
3. Confirma la eliminación.

### Asignar una tarjeta NFC a un cuento

1. En la sección "Biblioteca de Cuentos", localiza el cuento.
2. Pulsa **Asignar NFC** (o **Reasignar NFC** si ya tiene tarjeta).
3. Acerca la tarjeta NFC al robot.
4. El cuento quedará asociado a esa tarjeta.

---

### Tarjetas de parámetros (solo con IA)

Las tarjetas de parámetros permiten a los niños elegir ideas para que la IA cree un cuento nuevo.

#### Registrar una tarjeta de parámetro

1. En la sección "Tarjetas de Parámetros", pulsa **Registrar Parámetro**.
2. Acerca la tarjeta NFC al robot.
3. Rellena los campos:
   - **Categoría**: Tipo de parámetro (por ejemplo: "personaje", "lugar", "emoción").
   - **Valor**: El valor concreto (por ejemplo: "dragón", "bosque", "feliz").
   - **Emoji**: El icono que se mostrará.
   - **Etiqueta**: Nombre visible (por ejemplo: "Dragón").
4. Pulsa **Registrar**.

#### Registrar la tarjeta Go

1. En la sección "Tarjetas de Parámetros", pulsa **Registrar Go**.
2. Acerca la tarjeta NFC al robot.
3. Pulsa **Registrar** para confirmar.

#### Eliminar una tarjeta

En la lista de tarjetas registradas, pulsa **Eliminar** junto a la tarjeta que quieras quitar.

---

### Historias generadas por la IA (solo con IA)

Cuando los niños usan las tarjetas de parámetros y la tarjeta Go, la IA crea una historia nueva. Estas historias aparecen en la sección "Historias Generadas".

#### Ver una vista previa

1. Pulsa **Vista previa** en la tarjeta de la historia.
2. Verás los primeros caracteres del texto y la imagen de portada en una nueva pestaña.

#### Imprimir una pegatina para colorear

Las portadas generadas son **dibujos de línea en blanco y negro**, pensados para que los niños los coloreen después de escuchar el cuento.

1. Pulsa **Imprimir pegatina** en la tarjeta de la historia.
2. Se abrirá una ventana lista para imprimir con el dibujo.
3. Elige la impresora de pegatinas (Brother QL) y confirma la impresión.
4. Esta opción solo está disponible si la historia tiene imagen generada; si no, el botón aparece desactivado con el aviso "No hay portada para imprimir".

Si no se abre la ventana de impresión, el navegador está bloqueando las ventanas emergentes: permítelas para esta página y vuelve a intentarlo.

#### Promover una historia a la biblioteca

Para que una historia generada aparezca en el panel infantil como cuento normal:

1. Pulsa **Promover → Asignar** en la tarjeta de la historia.
2. Rellena los campos:
   - **Título**: Nombre del cuento (obligatorio).
   - **Emoji**: Icono del cuento.
   - **Color del LED**: Color de las luces durante la reproducción.
3. Pulsa **Promover y asignar tarjeta**.
4. Acerca la tarjeta NFC que quieres asociar a este cuento.

#### Descartar una historia

1. Pulsa **Descartar** en la tarjeta de la historia.
2. Confirma la eliminación.

---

### Configurar WiFi

1. En la sección "WiFi", pulsa para expandirla.
2. Pulsa **Actualizar** para buscar redes disponibles.
3. Selecciona una red de la lista:
   - Si la red es abierta, se conectará directamente.
   - Si la red está protegida, introduce la contraseña.
4. Pulsa **Conectar**.
5. Para desconectar, pulsa **Desconectar** junto a la red actual.

### Configurar Bluetooth

1. En la sección "Bluetooth", pulsa para expandirla.
2. Pulsa **Actualizar** para buscar dispositivos disponibles.
3. Selecciona un dispositivo:
   - **Emparejar**: Conecta un dispositivo nuevo.
   - **Conectar**: Conecta un dispositivo ya emparejado.
   - **Desconectar**: Desconecta el dispositivo actual.
   - **Olvidar**: Elimina un dispositivo emparejado.
4. El audio se reproducirá por el altavoz Bluetooth conectado.

### Instalar una actualización

1. Cuando haya una nueva versión, verás la sección "Actualizaciones" con el número de versión.
2. Pulsa **Instalar**.
3. Espera a que se complete el proceso:
   - Descargando...
   - Aplicando cambios...
   - Sincronizando dependencias...
   - Verificando...
   - Reiniciando StoryBot...
4. El robot se reiniciará automáticamente. Si tarda mucho, pulsa **Recargar** en el navegador.

---

## Solución de problemas

### El lector NFC no funciona
- Verifica que el icono de NFC en el panel de administración esté en verde.
- Si está en rojo, reinicia el robot y vuelve a comprobar.

### No se escucha el audio
- Comprueba que el altavoz esté bien conectado o emparejado por Bluetooth.
- En el panel de administración, revisa el icono de Bluetooth.

### La IA no genera historias
- Verifica que el panel de administración muestre "Modo: Completo".
- Si muestra "Modo: Básico (sin IA)", la inteligencia artificial no está disponible en este dispositivo.

### No se conecta al WiFi
- Asegúrate de introducir la contraseña correcta.
- Verifica que la red esté disponible y tenga señal suficiente.

### Un botón físico no hace nada
- **Botón de parar**: si el cuento sigue sonando, espera un segundo y vuelve a pulsar; si tampoco funciona, comprueba desde el panel que el robot responde (recarga `/admin`).
- **Botón de dibujo**: si la tira LED parpadea en ámbar, es que no hay ningún cuento sonando o el robot está en "Modo: Básico (sin IA)".
- **Botón de luces**: si no se ve el arcoíris, revisa el icono de la tira LED en el panel de administración (debe estar verde).
- **Botón de apagado**: si el robot no se apaga, es que el permiso de apagado no está configurado en el sistema; consulta con la persona que instaló el robot.

### El dibujo tarda mucho o no aparece
- Es normal que tarde entre uno y dos minutos; el cuento sigue sonando mientras tanto.
- Cuando el dibujo está listo, la tira LED hace un arcoíris. Si en lugar de eso se pone ámbar, la generación ha fallado: vuelve a pulsar el botón.
- Si el cuento tiene su propia portada subida, el dibujo **no** sustituye a la portada en pantalla, pero sí queda guardado para imprimirlo.

### Las luces no se encienden
- Revisa el icono de la tira LED en el panel de administración.
- Si está en rojo, apaga el robot, comprueba la conexión de la tira y vuelve a encenderlo.

---

## Especificaciones técnicas

- **Hardware**: NVIDIA Jetson Orin Nano Super 8GB
- **Sistema operativo**: Ubuntu 22.04 LTS
- **Modelos de IA**:
  - Texto: Qwen 2.5 3B Instruct (vía Ollama)
  - Voz: Piper TTS
  - Imágenes: Stable Diffusion 1.5
  - Transcripción de audio: whisper.cpp (en segundo plano, al subir un cuento)
- **Conexión**: 100% offline, sin necesidad de internet
- **Red propia**: punto de acceso WiFi "StoryBot" (`192.168.12.1`)
- **Lector NFC**: ACS ACR122U (USB)
- **Impresora**: Brother QL-820NWBc (pegatinas para colorear)
- **Tira LED**: 21 LEDs WS2812B
- **Botones físicos**: 4 (apagado, parar, dibujo, luces)
- **Pantalla**: Touchscreen HDMI de 7 pulgadas
