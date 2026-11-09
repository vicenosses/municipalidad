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

## Despliegue

La aplicación cuenta con una instalación desplegada en una instancia Amazon EC2. La configuración utilizada en AWS se encuentra separada de la configuración destinada al desarrollo local.

La instalación de AWS utiliza MariaDB y variables de entorno para sus datos de configuración.

## Autor

**Vicente Osses López**  
Analista Programador  
Programación Back End
