# Desarrollo de ci-diagnosis

Esta guía es para quien modifique la herramienta. Si eres alumno de la
asignatura, no necesitas nada de esto: lee el [README](README.md).

## Estructura

El programa que se distribuye (`ci-diagnosis`) **se genera**, no se edita a
mano. El código vive en `src/`, en fragmentos de un único programa:

```
src/base.py       Importaciones, resultados, salida y ejecutar() (órdenes externas)
src/textos.py     Secciones del manual y valores que espera el manual
src/claves.py     ~/.ssh/id_rsa e id_rsa.pub, agente (B7, B10, D6)
src/archivos.py   user-data, meta-data y network-config (B1, B4, B5, B6)
src/servidor.py   libvirt (solo lectura): silos, red, imagen y disco, nombres y
                  permisos (A1, A2, A3, B2, B3, B8, B9, C1, C2, D5)
src/main.py       Opciones y flujo principal
```

Tras modificar cualquiera de ellos, regenera el programa:

```bash
python3 tools/build.py
```

`tools/build.py` concatena los fragmentos en el orden de su lista `ORDEN`: todos
comparten el espacio de nombres, así que no se importan entre sí, y las
importaciones de la biblioteca estándar van todas en `base.py`. Un test
comprueba que `ci-diagnosis` está al día respecto a los fuentes.

## Tests locales (sin libvirt)

Con `unittest`, sobre el programa generado (que es lo que usa el alumnado), con
un libvirt simulado (`tests/falso_libvirt.py`) que solo tiene los métodos de
lectura: cualquier otro, o abrir una conexión de escritura, hace fallar el test.
Las imágenes se crean con el `qemu-img` de verdad (en macOS: `brew install qemu`). Las
claves SSH se generan al vuelo con `ssh-keygen` y el alumno de prueba es
`alu0000`: el repositorio es público, así que **ningún test ni ejemplo puede
llevar un UVUS real**.

Los servidores tienen Python 3.10 y PyYAML 5.4.1. En macOS, PyYAML 5.4.1 no se
compila con los Python recientes; con Python 3.11 y PyYAML 6 (misma interfaz
para lo que se usa):

```bash
python3.11 -m venv .venv && .venv/bin/pip install pyyaml==6.0.2
.venv/bin/python -m unittest discover -s tests
```

Con un Python sin PyYAML los tests también pasan: se saltan los que comprueban
la estructura de los archivos (`necesita_yaml`), y queda el que comprueba que la
herramienta avisa de que falta.

Para probar el programa a mano con otro usuario, `CI_DIAGNOSIS_USUARIO` sustituye
al de la cuenta (solo para pruebas; la herramienta solo lee, así que cambiarlo
no da acceso a nada).

## Lo que conviene saber antes de tocar el código

- **Solo lee.** La conexión a libvirt es `openReadOnly("qemu:///system")`: libvirt
  rechaza cualquier cambio. Las órdenes externas pasan todas por `ejecutar()`, que solo
  admite las de `ORDENES_PERMITIDAS` y las lanza sin teclado y con `LC_ALL=C`
  (warcry y megadeth responden en español). Los tests de `test_build.py`
  revisan el código: nada de `os.remove`, `os.chmod`… ni `open` para escribir,
  ni `subprocess` fuera de `ejecutar()`.
- **Nunca se muestra la clave privada.** De `id_rsa` solo se lee la cabecera
  (`analizar_privada`). Los errores de PyYAML se muestran con la línea y el
  problema, nunca con `str(e)`, que incluye el texto de la línea.
- **Gravedad.** ERROR cuando el efecto se conoce; AVISO cuando solo se aparta
  del manual y el efecto no está comprobado; `--` (`omitida`) cuando no se
  puede comprobar porque falla algo de lo que depende. Solo ERROR cambia el
  código de salida.
- **Mensajes del sistema.** Los que se citan en los textos tienen que estar
  grabados en el servidor (por ejemplo, `Permission denied (publickey)`). Si
  no lo están, se describe el efecto sin citar.
- **Silos por trayecto.** Los nombres de los silos no identifican al dueño
  (hay erratas y variantes): todo se decide por el trayecto real (`realpath`).
- **Permisos, no dueños.** libvirt cambia el dueño de la imagen base y del disco
  al encender la máquina (`libvirt-qemu kvm`), pero no los permisos; al
  apagarla, el disco vuelve al alumno y la imagen base no. Por eso se avisa
  por los permisos, sea quien sea el dueño.
- **El manual.** Todas las referencias van por `SECCIONES` (`textos.py`): si
  cambia la numeración, se cambia solo esa tabla.
- **«Cómo arreglarlo»** es un campo aparte (`arreglo`): con
  `MOSTRAR_ARREGLO = False` la herramienta solo señala los fallos.
- **Python 3.8 como mínimo.** Un test lo comprueba con
  `ast.parse(..., feature_version=(3, 8))`, pero no detecta funciones nuevas de
  la biblioteca (`str.removeprefix`, por ejemplo): no las uses.
