OGA SISTEMVAC - REV15 / BIBLIOTECA INTEGRADA
Fecha de entrega: 16 de septiembre de 2026
Base: GENERADOR_RQ_AV_REV14_ESTETICA(2).zip + oga_biblio_v6.zip.001 a .005

INICIO
======
1. Cierre la REV14 antes de iniciar la REV15: ambas usan el puerto 5005.
2. Descomprima TODO este ZIP en una carpeta nueva. No trabaje dentro del ZIP.
3. Abra la carpeta completa en Visual Studio Code.
4. Ejecute INICIAR.py, o use F5 con la configuracion incluida.
   Desde la terminal de esa carpeta tambien puede ejecutar:

       python INICIAR.py

5. El lanzador revisa las dependencias (ahora incluye pandas). Si no encuentra
   un Python preparado, crea .venv e instala requirements.txt. Esa primera
   instalacion necesita Internet. El entorno virtual NO viene dentro del ZIP.
6. Abra http://127.0.0.1:5005 si el navegador no se abre automaticamente.
   Ingrese con sus usuarios habituales de la REV14 enviada.

Esta es una version de codigo fuente, como la pagina REV14; NO es un nuevo EXE
ni necesita archivos .bat. No ejecute OGA_Biblioteca.exe para abrir la REV15.
No publique este paquete en un repositorio publico: incluye datos internos.

MODULOS
=======
- Lista Maestra sigue como acceso independiente al comienzo del menu.
- Se conservan Generador de RQ y Revisor de Planos.
- Nuevo grupo desplegable BIBLIOTECA:
  * Biblioteca de equipos: equipos, caracteristicas, subcaracteristicas,
    referencias, costos por referencia y documentos asociados.
  * Buscador de referencias: filtros dependientes, consulta, vista PDF y descarga.
  * Costos: importacion masiva desde Excel con columnas referencia y costo.
- Biblioteca utiliza el mismo inicio de sesion, cierre de sesion y token de
  seguridad de la pagina principal. Las descargas no son publicas.
- Los usuarios autenticados comparten el catalogo de Biblioteca; no se mezcla
  con las carpetas de trabajo individuales de RQ. No se agregaron roles nuevos.
- Fuente del sistema tipo GitHub/Primer, con pesos 400, 500 y 600. En Windows
  se utiliza Segoe UI cuando esta disponible. No se incluyen archivos de fuente
  ni dependencias de Google Fonts o Font Awesome para Biblioteca.

INFORMACION CONSERVADA
=====================
Biblioteca queda en data/BIBLIOTECA/:
  equipos.xlsx:          63 equipos.
  caracteristicas.xlsx: 307 caracteristicas, con sus subcaracteristicas.
  referencias.xlsx:     184 referencias.
  costos.xlsx:            3 registros de costos originales.
  archivos/planos_pdf/: 185 PDF conservados.

Los 188 archivos de data de Biblioteca original se conservaron byte por byte.
Se rescato ademas FDV1324784.pdf, que SOLO estaba en _internal/data. No se creo
una referencia ficticia para ese documento; se conserva el archivo sin alterar
el catalogo. Los 184 PDF asociados a las referencias estan presentes.

Los datos de RQ, usuarios, configuracion, Lista Maestra, trabajos y documentos
son los que venian en la REV14 que usted envio. No se restablecieron cuentas,
no se cambiaron contrasenas y no se alteraron las reglas de calculo de RQ.

SI SIGUIO TRABAJANDO DESPUES DE ENVIAR LA REV14
===========================================
El ZIP es una copia de los datos recibidos, no una sincronizacion con su PC.
Antes de reemplazar una instalacion, cierre las aplicaciones y haga una copia
completa de la carpeta actual. Para conservar trabajo mas reciente, copie el
contenido actualizado de data de su REV14 sobre data de la REV15 SIN borrar
ni reemplazar la carpeta nueva data/BIBLIOTECA. Pruebe siempre en una copia.
Mantenga intacta la instalacion anterior hasta confirmar el funcionamiento.

ADJUNTOS Y COSTOS
================
Se mantienen los formatos del modulo v6:
  planos: PDF; modelo 3D: ZIP; lista de materiales: XLSM; ficha tecnica: DOCX.
El nombre del archivo debe coincidir con el codigo de la referencia.
La carga masiva de costos REEMPLAZA el listado completo, como en v6: no suma
registros al listado anterior. Se agrego una advertencia antes de confirmar.
El limite de carga de la aplicacion sigue siendo 96 MiB por solicitud, como
estaba definido en REV14. No esta relacionado con el limite de adjuntos del chat.

RESPALDOS
=========
Guarde una copia de TODA la carpeta data/BIBLIOTECA para respaldar su catalogo.
Los botones de Archivar/Copias de seguridad del Generador de RQ conservan su
alcance anterior: no son una copia completa de Biblioteca. Por eso no aparecen
las acciones Nueva lista y Archivar de RQ en las pantallas de Biblioteca.
Cierre los Excel de Biblioteca en Microsoft Excel antes de editar por la web.
Los guardados se serializan dentro de un proceso y se reemplazan de manera
atomica. No ejecute dos instancias de la aplicacion sobre los mismos archivos.

VERIFICACION
============
Se ejecutaron 56 comprobaciones funcionales en una copia temporal y los 7 tests
originales de reglas de RQ. El registro esta en documentacion/PRUEBAS_REV15.txt.
Para repetir la verificacion con el entorno instalado:

       python VALIDAR_REV15.py

La validacion crea una copia temporal y cuentas de prueba temporales; no cambia
sus datos reales. Se verifico tambien el renderizado de la interfaz con Chromium
sin conexion a servicios externos. No se ejecuto Windows en este entorno:
confirme el arranque y la visualizacion nativa de PDF en su propio navegador.

POR QUE EL ARCHIVO PESABA TANTO
==============================
Lea documentacion/INFORME_TAMANO_BIBLIOTECA.txt. El paquete enviado mezclaba el
codigo fuente, el historial de Git, el EXE, su runtime, datos duplicados y archivos
de compilacion. El codigo de Biblioteca en si ocupa aproximadamente 66 kB.
