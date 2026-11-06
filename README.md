# ci-diagnosis

### Diagnóstico de máquinas virtuales construidas con cloud-init
**Asignatura: Sistemas Operativos — Universidad de Sevilla**

> **En desarrollo.** Todavía no está disponible en los servidores de la asignatura.

`ci-diagnosis` revisa, en el servidor de la asignatura, la construcción de una
máquina virtual con cloud-init siguiendo el manual (sección 5.4) y dice qué
falla, por qué y en qué sección del manual se explica.

Sirve en dos momentos:

- **Antes de `virt-install`:** el silo, la red, la imagen base y el disco, los
  archivos `user-data`, `meta-data` y `network-config`, y las claves SSH.
- **Cuando no se puede entrar en la máquina:** su estado, la red, el acceso por
  SSH y, con la máquina apagada, lo que cloud-init dejó escrito en su disco.

Se ejecuta con la cuenta del alumno, sin `sudo`, y **solo lee**: no cambia
archivos, no arranca ni apaga máquinas y no toca silos ni redes.

La creación automática de máquinas está en
[ci-provision](https://github.com/davgutavi/ci-provision).

## Licencia

[MIT](LICENSE)
