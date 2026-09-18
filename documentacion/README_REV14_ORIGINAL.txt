OGA SISTEMVAC - GENERADOR DE RQ - REV 14
==========================================

INICIO EN VISUAL STUDIO CODE
----------------------------
1. Descomprima la carpeta completa GENERADOR_RQ_AV_REV13_LOGIN.
2. Abra esa carpeta en Visual Studio Code.
3. Presione F5.
4. Ejecute INICIAR.py si VS Code lo solicita.

NO ES NECESARIO EJECUTAR ARCHIVOS .BAT.
La REV 13 incluye INICIAR.py. En el primer arranque crea automáticamente una carpeta .venv
local e instala dentro de ella únicamente las dependencias que necesite el programa.
Esto no modifica las bases del programa ni configura servidores externos.

Dirección local: http://127.0.0.1:5005

PRIMER INICIO Y USUARIOS
------------------------
1. En el primer inicio aparece una única pantalla para crear el administrador permanente.
2. No hay registro público ni recuperación de contraseña.
3. El administrador crea, desactiva, cambia de rol y restablece contraseñas desde USUARIOS.
4. Las contraseñas no se pueden consultar después de guardarlas; se conservan como hash Argon2id.
5. USUARIOS.xlsx y AUDITORIA.xlsx se crean automáticamente dentro de data/SEGURIDAD.

La cuenta inicial no es temporal y no vence a las 24 horas. El sistema impide desactivar o
degradar al último administrador activo para evitar quedarse sin acceso administrativo.

SEGURIDAD E INSTALACIÓN EN EL SERVIDOR
--------------------------------------
- Configure permisos de Windows para que data/SEGURIDAD solo pueda leerla la cuenta que
  ejecuta el servicio y los responsables autorizados. No comparta esa carpeta en la red.
- Publique la aplicación con HTTPS mediante IIS u otro proxy interno y defina OGA_HTTPS=1.
- Para escuchar en la red local, defina OGA_HOST=0.0.0.0 y permita el puerto únicamente
  desde la red empresarial. No exponga directamente el puerto 5005 a Internet.
- Use una sola instancia/proceso de la aplicación. Waitress administra varios usuarios
  mediante hilos y los archivos Excel se escriben con exclusión mutua y reemplazo atómico.
- Incluya toda la carpeta data en la copia de seguridad diaria del servidor.

Cada usuario tiene separados su trabajo actual, históricos, copias y planos dentro de
data/USUARIOS. La Lista Maestra, el calendario y los festivos son recursos compartidos.


CAMBIO PRINCIPAL REV 14
-----------------------
Rediseño exclusivamente visual: nueva navegación lateral, grupos desplegables para RQ y Planos,
Lista Maestra como primer acceso independiente, portada y login renovados, y microanimaciones.
La lógica de negocio y las funciones de la REV 13 se conservan sin cambios.

CAMBIO PRINCIPAL REV 13
-----------------------
Inicio de sesión obligatorio, roles ADMINISTRADOR/COLABORADOR, gestión de usuarios,
bloqueo después de cinco intentos fallidos, límite por IP, expiración por inactividad,
protección CSRF, auditoría en Excel y espacios de trabajo independientes por usuario.

CAMBIO PRINCIPAL REV 12
-----------------------
Se conservan los arreglos de búsqueda, cargas de archivos y flujo de la versión entregada.

CAMBIO PRINCIPAL REV 11
-----------------------
El módulo PLANOS usa el visor PDF tradicional del navegador. Permite escribir el número
de hoja, usar miniaturas, búsqueda, zoom, impresión y abrir el documento en otra pestaña.

CAMBIO PRINCIPAL REV 10
-----------------------
Todo nombre que contenga A/C en cualquier posición se clasifica como EXTERNO.

CAMBIO PRINCIPAL REV 09
-----------------------
La RQ se presenta en listas separadas por clasificación y cada clasificación puede
exportarse a un archivo Excel independiente. SIN CLASIFICAR queda en rojo y al final.

CAMBIO PRINCIPAL REV 08
-----------------------
Nueva identidad visual inspirada en la página corporativa de OGA: cabecera blanca,
portada azul institucional y áreas de trabajo claras para tablas y formularios.
Se conservan el AUTOGUARDADO y los puntos de recuperación incorporados en la REV 07.

CAMBIO PRINCIPAL REV 07
-----------------------
Se agregó AUTOGUARDADO con hasta 10 puntos de recuperación. El sistema crea copias
después de cargar o procesar información y antes de acciones destructivas como NUEVA LISTA.
La pantalla COPIAS permite crear, restaurar y eliminar puntos de recuperación.

CAMBIO PRINCIPAL REV 06
-----------------------
Se incorporó la primera versión de la interfaz corporativa y su navegación.

CAMBIO PRINCIPAL REV 05
-----------------------
Se eliminó completamente la lectura de PDF para el Listado Gráfico de Entregables.
Ahora el listado superior de equipos se carga desde un Excel exportado desde Inventor.
Columnas requeridas:
- PART NUMBER
- DESCRIPTION
- STOCK NUMBER
- ITEM QTY

El programa usa STOCK NUMBER como código del equipo (si está vacío usa PART NUMBER),
DESCRIPTION como descripción e ITEM QTY como cantidad. Después despliega una fila por equipo
para cargar su lista detallada de Inventor. Se conserva la opción ELIMINAR para excluir equipos
antes de PROCESAR.

FLUJO RECOMENDADO
-----------------
1. Cargar el Excel superior de equipos desde Inventor si se trabajará discriminado por equipo.
2. Cargar una lista de Inventor por cada equipo detectado.
   Alternativamente, cargar una LISTA DE INVENTOR general si no se requiere desglose por equipo.
3. Cargar B1 directo de Factory (.XLS o .XLSX).
4. Presionar PROCESAR.
5. Revisar RQ, LM, REPUESTOS y VALOR.
6. Cargar movimientos/RQ reales para verificar y descontar lo efectivamente realizado.
7. ARCHIVAR solo cuando se desee conservar el trabajo en HISTÓRICO.

LISTA MAESTRA FACTORY
---------------------
La Lista Maestra Factory es permanente y no se elimina al usar NUEVA LISTA.
Los códigos existentes se editan directamente en el Excel maestro y luego se usa
ACTUALIZAR DESDE EXCEL. El programa solo permite crear códigos nuevos.

B1
--
El programa conserva únicamente filas cuyo CODIGO esté compuesto 100 % por números.
Muestra CODIGO, NOMBRE, UD y EXISTENCIA.

REGLAS FIJAS
------------
1 - PERFIL / TRAMOS DE 6 m
2 - REDONDOS
3 - CANTIDAD / 2
4 - LÁMINA 4 x 8 FT
5 - LÁMINA 5 x 10 FT
6 - LÁMINA 5 x 20 FT
7 - LÁMINA 1 x 3 m
8 - MATERIAL LINEAL: longitud indicada + 10 mm por pieza, consolidada en metros

Las reglas de lámina se deducen del formato comercial escrito en NOMBRE.
Para referencias cuya unidad maestra es M, el programa también reconoce perfiles,
ángulos, platinas, redondos, tuberías, mangueras, empaques lineales y espárragos.
Los perfiles, ángulos y platinas se redondean a tramos de 6 m; las tuberías y otros
materiales lineales se conservan en metros porque su largo comercial puede variar.

DEPENDENCIAS
------------
Flask, openpyxl, xlrd, PyMuPDF, argon2-cffi y Waitress. INICIAR.py las administra
automáticamente dentro de .venv.
