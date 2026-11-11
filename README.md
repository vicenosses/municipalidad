# Sistema de Gestión de Resultados Municipal

Aplicación web desarrollada para apoyar la gestión y el seguimiento de actividades de la Ilustre Municipalidad de La Serena.

El sistema centraliza información relacionada con usuarios, delegaciones, actividades, evidencias, compromisos, metas e indicadores. Cada usuario accede a las funciones disponibles para su rol y delegación.

## Objetivo

Facilitar el registro, la organización y el seguimiento de la información municipal mediante una aplicación web con acceso controlado y almacenamiento en una base de datos relacional.

## Funcionalidades

- Inicio y cierre de sesión.
- Recuperación de contraseña por correo electrónico.
- Gestión de usuarios, roles, cargos y delegaciones.
- Registro y seguimiento de actividades.
- Administración de tipos y subtipos de atención.
- Registro y validación de evidencias.
- Gestión de compromisos y solicitudes de ampliación de plazo.
- Administración de períodos, metas e indicadores SGR.
- Registro de acciones relevantes mediante auditoría.
- Eliminación de registros para el administrador, con restricciones cuando existen datos relacionados.

## Roles

El sistema considera los siguientes roles:

- **Administrador:** gestión general y acceso a las funciones administrativas.
- **Delegado:** gestión de funciones y usuarios dentro de su delegación.
- **Coordinador:** supervisión y gestión de las funciones autorizadas.
- **Verificador:** revisión de evidencias y otras solicitudes autorizadas.
- **Funcionario:** registro y consulta de información relacionada con su trabajo.

Los accesos dependen del rol, la delegación y las restricciones implementadas en cada función.

## Tecnologías utilizadas

- Python.
- Django.
- Django Templates.
- Django ORM.
- HTML, CSS y Bootstrap.
- MariaDB o MySQL para el entorno configurado con ese motor.
- SQLite como alternativa para desarrollo local.
- Git y GitHub.
- Amazon Web Services EC2.
- Herramientas de inteligencia artificial como apoyo al desarrollo.

## Requisitos

Para ejecutar el proyecto localmente se necesita:

- Python 3.11.
- Git.
- Una base de datos SQLite, o un servidor MariaDB/MySQL si se desea utilizar ese motor.
- Una cuenta de correo configurada para probar el envío de mensajes de recuperación.

## Instalación local en Windows

1. Clonar el repositorio y entrar a la carpeta:

```powershell
git clone https://github.com/vicenosses/municipalidad.git
cd municipalidad
```

2. Crear y activar un entorno virtual:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
```

3. Instalar las dependencias:

```powershell
python -m pip install -r requirements.txt
```

4. Crear el archivo de configuración local a partir de la plantilla:

```powershell
Copy-Item .env.aqui .env
```

5. Generar una clave para Django:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Copiar el resultado en el archivo `.env`, después de `DJANGO_SECRET_KEY=`. No compartir esta clave ni subir el archivo `.env` a GitHub.

6. Para utilizar SQLite en el computador, mantener esta opción en el archivo `.env`:

```text
DB_ENGINE=sqlite
```

Si se utiliza MariaDB o MySQL, configurar `DB_ENGINE=mysql` y completar los datos de conexión correspondientes en el archivo `.env`.

7. Crear las tablas de la base de datos:

```powershell
python manage.py migrate
```

8. Crear el primer usuario administrador:

```powershell
python manage.py createsuperuser
```

9. Iniciar la aplicación:

```powershell
python manage.py runserver
```

10. Abrir en el navegador:

```text
http://127.0.0.1:8000/
```

## Configuración del correo

Para enviar correos de recuperación, completar las variables de correo en el archivo `.env`. Si se utiliza Gmail, se debe configurar una **contraseña de aplicación** y no la contraseña habitual de la cuenta.

Si no se va a configurar el envío durante el desarrollo, dejar `EMAIL_HOST` vacío para que los mensajes se muestren en la consola.

No publicar contraseñas, claves de aplicación ni el archivo `.env` en el repositorio.

## Base de datos

El proyecto utiliza modelos y migraciones de Django para definir y actualizar la estructura de la base de datos.

Entre las entidades principales se encuentran:

- Usuarios y perfiles.
- Roles y delegaciones.
- Actividades y evidencias.
- Compromisos y solicitudes de ampliación.
- Períodos, metas e indicadores.
- Registros de auditoría.

## API REST v1

La API JSON está disponible en `/api/v1/`. Al abrir esa dirección con una sesión válida se muestra el índice navegable de Django REST Framework. Las operaciones de negocio reutilizan las reglas y cálculos actuales del sistema.

### Autenticación

Salvo la obtención de token y la solicitud de recuperación, los endpoints requieren una sesión autenticada o un token JWT:

1. Solicita tokens con `POST /api/v1/auth/token/` y un JSON con `username` y `password`. El valor de `username` también puede ser el correo registrado.
2. Envía el token de acceso en cada solicitud protegida: `Authorization: Bearer <access>`.
3. Renueva con `POST /api/v1/auth/token/refresh/` y `{"refresh": "<refresh>"}`. El refresh se rota y el anterior queda invalidado.
4. Cierra la sesión del token con `POST /api/v1/auth/logout/`, el mismo encabezado Bearer y `{"refresh": "<refresh>"}`.
5. Solicita recuperación con `POST /api/v1/auth/recuperacion/` y `{"identificador": "<correo o usuario>"}`. La respuesta es igual exista o no la cuenta.

Los access tokens vencen en 15 minutos y los refresh en 24 horas. Los intentos fallidos comparten el bloqueo de acceso existente y los endpoints de autenticación tienen límites de solicitudes.

### Recursos

| Endpoint | Uso |
|---|---|
| `/yo/` | Perfil autenticado, rol y delegaciones autorizadas. |
| `/delegaciones/`, `/territorios/` | Catálogos acotados a las delegaciones permitidas. |
| `/cargos/`, `/roles/` | Catálogos administrativos; nunca se exponen las reglas internas de permisos. |
| `/tipos-atencion/`, `/subatenciones/`, `/vecinos/?q=...` | Catálogos y búsqueda/autocompletado de vecinos. |
| `/periodos/`, `/metas/`, `/asignaciones/`, `/indicadores/` | Estructura y asignaciones del SGR. |
| `/actividades/`, `/compromisos/`, `/ampliaciones/` | Actividades, tubo de compromisos y solicitudes de ampliación. |
| `/evidencias/`, `/aportes/` | Evidencias y propuestas/revisiones de aportes a indicadores. |
| `/gestiones-sociales/`, `/cartas/`, `/hitos/` | Seguimiento social, cartas y etapas de seguimiento. |
| `/tubo/` | Vista unificada de actividades, compromisos, gestiones sociales y cartas. |
| `/dashboard/` | Indicadores agregados y semáforo del período vigente. |
| `/auditoria/` | Bitácora, disponible solo para administración. |

Los listados están paginados (50 elementos como máximo por página). El tubo acepta `tipo`, `estado`, `q`, `desde` y `hasta`; las fechas usan `AAAA-MM-DD`. La búsqueda de vecinos requiere `q` y devuelve solo el nombre abreviado, el RUT enmascarado y el territorio.

### Operaciones de escritura principales

- `POST /actividades/` registra una actividad usando las mismas validaciones de tipos, subtipos, territorio, indicadores y evidencias que el formulario web. Acepta los campos del formulario `AtencionCiudadanaForm`; si `va_al_tubo` es verdadero, también requiere `plazo_tubo`.
- `POST /actividades/{id}/estado/`, `/tubo/` y `/disponibilidad/` ejecutan las transiciones autorizadas.
- `POST /compromisos/` registra compromisos y sus relaciones con actividades. `POST /compromisos/{id}/solicitar-ampliacion/` crea una solicitud; `POST /ampliaciones/{id}/decision/` recibe `{"accion": "aprobar"}` o `{"accion": "rechazar"}`.
- `POST /evidencias/` carga una evidencia `multipart/form-data` vinculada a exactamente una actividad o compromiso. El archivo se entrega solo por `GET /evidencias/{id}/archivo/` después de comprobar el acceso. La validación se efectúa en `POST /evidencias/{id}/validar/`.
- `POST /aportes/proponer/` recibe `actividad`, `indicador`, `valor_declarado` y `version`; `POST /aportes/{id}/validar/` aplica la revisión del SGR con control de concurrencia.
- Gestión Social, Cartas e Hitos aceptan creación y edición sin borrado físico. Sus estados solo cambian mediante `POST /{id}/estado/`; cada transición permitida se registra en auditoría.

Ejemplo mínimo de gestión social:

```json
{
  "titulo": "Orientación vecinal",
  "tipo": "orientacion",
  "descripcion": "Antecedentes de la gestión",
  "delegacion": 1,
  "territorio": 1,
  "ingresa_al_tubo": true
}
```

Los códigos de Gestión Social, Cartas e Hitos se generan automáticamente. Un Hito debe estar asociado a exactamente una actividad, gestión social o compromiso.

### Pantallas web de operación

Gestión Social se encuentra dentro de **Actividades**, en la navegación secundaria de esa sección. El Tubo de cartas y los Hitos se encuentran dentro de **Agenda**, junto a Compromisos; no agregan opciones al panel lateral. Los listados y detalles aplican el contexto territorial, y los funcionarios solo ven los registros propios o a su cargo. Administradores, delegados y coordinadores pueden consultar la información de sus ámbitos autorizados. La creación de Hitos está limitada a administradores y delegados.

### Acceso y datos personales

La API requiere roles activos y filtra los registros por las delegaciones autorizadas en el servidor; nunca confía en un ID de delegación enviado por el cliente sin validarlo. Los funcionarios y verificadores solo gestionan sus registros sensibles. Los listados omiten contenido de gestión/carta, descripciones de actividad y datos del solicitante; los detalles sensibles quedan limitados a responsables, verificadores y gestores autorizados. Los RUT que devuelve la búsqueda están enmascarados, y los archivos de evidencia no son públicos. No se registra el contenido de gestiones, cartas ni RUT en la nueva bitácora.

Para permitir acceso desde un cliente web de otro origen, agregue sus orígenes HTTPS a `CORS_ALLOWED_ORIGINS`, separados por coma. La lista está vacía de forma predeterminada. No se habilita CORS indiscriminadamente.

## Despliegue

La aplicación cuenta con una instalación desplegada en una instancia Amazon EC2. La configuración utilizada en AWS se encuentra separada de la configuración destinada al desarrollo local.

La instalación de AWS utiliza MariaDB y variables de entorno para sus datos de configuración.

## Autor

**Vicente Osses López**  
Analista Programador  
Programación Back End
