# ci-diagnosis

### Diagnóstico de máquinas virtuales construidas con cloud-init
**Asignatura: Sistemas Operativos — Universidad de Sevilla**

`ci-diagnosis` revisa, en el servidor de la asignatura, la construcción de una
máquina virtual con cloud-init siguiendo el manual (sección 5.4) y le dice qué
falla, por qué, cómo arreglarlo y en qué sección del manual se explica.

**Solo lee.** No cambia ningún archivo, no arranca ni apaga máquinas, no toca
silos ni redes y no muestra nunca su clave privada. Se ejecuta con su cuenta,
sin `sudo`.

## Cómo se descarga

En el servidor, descárguela en su silo y dele permiso de ejecución:

```
cd ~/imagenesMV
wget https://raw.githubusercontent.com/davgutavi/ci-diagnosis/main/ci-diagnosis -O ci-diagnosis && chmod u+x ci-diagnosis
```

Con `curl`: `curl -L https://raw.githubusercontent.com/davgutavi/ci-diagnosis/main/ci-diagnosis -o ci-diagnosis && chmod u+x ci-diagnosis`.

Para tener la última versión, repita la descarga: con `-O ci-diagnosis`, `wget`
sobrescribe la que tenía (sin `-O`, guardaría la nueva como `ci-diagnosis.1`).
Para ver qué versión tiene: `./ci-diagnosis --version`.

## Cómo se usa

Ejecútela en el servidor, desde su silo:

```
cd ~/imagenesMV
./ci-diagnosis server1
```

Sustituya `server1` por la máquina que quiere revisar (también vale `1` o
`su_uvus-server1`). Si no indica ninguna, se toma del `local-hostname` de su
archivo `meta-data`.

Según la situación, hace una de dos revisiones:

- **Antes de `virt-install`** (la máquina todavía no existe): su silo, su red,
  la imagen base y el disco, los archivos `user-data`, `meta-data` y
  `network-config`, sus claves SSH, que el nombre y la IP estén libres, los
  permisos de su directorio personal y, si ya intentó crear la máquina, qué dijo
  `virt-install`.
- **Con la máquina ya creada**, en cinco bloques:
  1. **Máquina y red:** si está encendida, si está conectada a su red, cómo
     es su red, su IP y si responde en ella (ping y puerto 22).
  2. **Disco:** su formato, su tamaño y la imagen de la que depende y, con la
     máquina apagada, lo que cloud-init dejó escrito en él: el usuario, la
     clave y la red que configuró, y sus errores.
  3. **Claves SSH y acceso:** sus claves y si `ssh` puede entrar, y por qué no.
  4. **Orden de virt-install:** la orden con la que creó la máquina, tal como
     la escribió (la toma de su registro), comparada opción por opción con la
     del manual.
  5. **Archivos de cloud-init:** `user-data`, `meta-data` y `network-config`.

Elige sola: si la máquina existe, la segunda; si no, la primera. Puede forzarla
con `--antes` o con `--acceso`.

Si la máquina está encendida y no puede entrar, la herramienta le pedirá que la
apague (`virsh shutdown`) y que la vuelva a ejecutar: así puede revisar su
disco. Ella nunca la apaga.

Otras opciones:

```
./ci-diagnosis server1 --ip 192.168.XXX.YYY   # si la IP no es la de su network-config
./ci-diagnosis --ayuda
```

## Lo que no revisa

La conexión desde su ordenador hasta el servidor: sus claves y su agente en el
ordenador, `virt-manager` o un bloqueo del servidor por demasiados intentos
fallidos. Si no puede conectarse al servidor, consulte la sección 4.5 del manual
y la FAQ.

`ci-diagnosis` tampoco cuenta nunca como un intento fallido: para comprobar si
puede entrar en su máquina usa solo su clave, nunca una contraseña.

## Cómo leer el resultado

Cada comprobación da una de estas respuestas:

| | |
|---|---|
| `OK` | Está bien. |
| `AVISO` | Se aparta del manual o puede dar problemas, pero no impide seguir. |
| `ERROR` | Está mal: hay que arreglarlo. |
| `--` | No se ha podido comprobar, porque falla algo de lo que depende. |

Los avisos y errores llevan, debajo, el efecto, cómo arreglarlo y la sección del
manual. Las soluciones llevan sus nombres reales (su UVUS, su máquina, su IP) y
las órdenes completas, cada una en su línea, listas para copiar. Cuando la única
solución es volver a crear la máquina, se dan todos los pasos: eliminarla con su
disco, crear un disco nuevo, la orden de `virt-install` del manual y olvidar la
huella antigua de `ssh`. Algunos llevan también, entre corchetes, el código del fallo (`[B5]`):
indíquelo si pregunta en el chat de dudas.

Empiece siempre por el **primer ERROR**: los demás pueden ser consecuencia suya.

Un ejemplo (de una prueba, con el usuario cambiado):

```
ARCHIVOS DE CLOUD-INIT
  OK     Existe user-data
  ERROR  user-data tiene comillas curvas (línea 4) [B1]
         Caracteres: U+2018, U+2019; la comilla es «'».
         Cómo arreglarlo: suele pasar al copiar del PDF o de la web. Escriba
         esa parte a mano con nano.
         Manual: sección 5.4.1 (Pasos preliminares)
```

Si la salida le dice «avise al profesor», el problema no es suyo (por ejemplo, un
silo de otro usuario que hace fallar `virt-install` a todos): comuníqueselo a su
profesor tal cual.

El código de salida es 0 si no hay ningún ERROR, 1 si hay alguno y 2 si la
herramienta no ha podido hacer la revisión.

## Para el profesorado: revisar la cuenta de un alumno

`tools/ci-diagnosis-admin` lanza la misma revisión sobre la cuenta de un alumno,
como si la ejecutara él. Necesita `sudo`, así que solo sirve al profesorado.

Una vez, en el servidor, en `~/bin` (Ubuntu lo añade al `PATH` al iniciar
sesión, si existe):

```
mkdir -p ~/bin && wget -q https://raw.githubusercontent.com/davgutavi/ci-diagnosis/main/tools/ci-diagnosis-admin -O ~/bin/ci-diagnosis-admin && chmod 755 ~/bin/ci-diagnosis-admin && ~/bin/ci-diagnosis-admin --actualizar
```

Después, para revisar a un alumno:

```
ci-diagnosis-admin UVUS            # la máquina de su meta-data
ci-diagnosis-admin UVUS server2    # otra máquina
```

Muestra sus silos y sus máquinas, elige el directorio en el que trabaja (su silo
`UVUS-imagenesMV`, o `~/imagenesMV`; `--dir` para indicar otro) y ejecuta
`ci-diagnosis` como el alumno con `sudo`, que pide su contraseña. Solo lee:
no cambia nada en su cuenta. `ci-diagnosis-admin --actualizar` descarga la
última versión de los dos programas.

## Para quien la desarrolle

Lea [DESARROLLO.md](DESARROLLO.md).

## Licencia

[MIT](LICENSE)
