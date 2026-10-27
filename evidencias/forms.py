from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

from atenciones.models import AtencionCiudadana
from agenda.models import Compromiso
from evidencias.models import Evidencia
from evidencias.permisos import puede_agregar_evidencia, registros_cargables


TIPOS_ARCHIVO = {
    '.jpg': ('imagen', 'image/jpeg'),
    '.jpeg': ('imagen', 'image/jpeg'),
    '.png': ('imagen', 'image/png'),
    '.webp': ('imagen', 'image/webp'),
    '.mp4': ('video', 'video/mp4'),
    '.webm': ('video', 'video/webm'),
}


def validar_archivo(archivo, extensiones_permitidas=None):
    extension = Path(archivo.name).suffix.lower()
    if extension not in TIPOS_ARCHIVO or (
        extensiones_permitidas is not None and extension not in extensiones_permitidas
    ):
        raise ValidationError('Formato no permitido. Use JPG, JPEG, PNG, WebP, MP4 o WebM según corresponda.')
    tipo, mime_esperado = TIPOS_ARCHIVO[extension]
    if getattr(archivo, 'content_type', '') != mime_esperado:
        raise ValidationError('El tipo de contenido no coincide con la extensión del archivo.')

    limite_mb = (
        settings.EVIDENCIA_MAX_VIDEO_MB if tipo == 'video' else settings.EVIDENCIA_MAX_IMAGE_MB
    )
    if archivo.size > limite_mb * 1024 * 1024:
        raise ValidationError(f'El archivo supera el máximo permitido de {limite_mb} MB.')

    try:
        archivo.seek(0)
        if tipo == 'imagen':
            with Image.open(archivo) as imagen:
                formatos = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}
                if imagen.format != formatos[extension]:
                    raise ValidationError('El contenido real no coincide con la extensión del archivo.')
                imagen.verify()
        else:
            if extension == '.mp4':
                _validar_mp4(archivo)
            else:
                _validar_webm(archivo)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise ValidationError('No se pudo validar el contenido real del archivo.') from error
    finally:
        archivo.seek(0)


def _validar_mp4(archivo):
    tamano = archivo.size
    cabecera = archivo.read(16)
    marcas = {b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V ', b'dash', b'qt  '}
    if (
        len(cabecera) < 16
        or cabecera[4:8] != b'ftyp'
        or cabecera[8:12] not in marcas
        or int.from_bytes(cabecera[:4], 'big') < 16
    ):
        raise ValidationError('El archivo no tiene una cabecera MP4 válida.')

    posicion = int.from_bytes(cabecera[:4], 'big')
    if posicion > tamano:
        raise ValidationError('La cabecera MP4 excede el tamaño del archivo.')
    hay_moov = False
    hay_mdat = False
    while posicion < tamano:
        archivo.seek(posicion)
        caja = archivo.read(8)
        if len(caja) != 8:
            raise ValidationError('El archivo MP4 contiene una caja incompleta.')
        longitud = int.from_bytes(caja[:4], 'big')
        tipo = caja[4:8]
        cabecera_caja = 8
        if longitud == 1:
            extendida = archivo.read(8)
            if len(extendida) != 8:
                raise ValidationError('El archivo MP4 contiene una caja incompleta.')
            longitud = int.from_bytes(extendida, 'big')
            cabecera_caja = 16
        elif longitud == 0:
            longitud = tamano - posicion
        if longitud < cabecera_caja or posicion + longitud > tamano:
            raise ValidationError('El archivo MP4 contiene una caja con tamaño inválido.')
        hay_moov |= tipo == b'moov'
        hay_mdat |= tipo == b'mdat' and longitud > cabecera_caja
        posicion += longitud
    if not (hay_moov and hay_mdat):
        raise ValidationError('El archivo no contiene estructura de video MP4 válida.')


def _validar_webm(archivo):
    archivo.seek(0)
    cabecera = archivo.read(4096)
    if not (
        cabecera.startswith(b'\x1a\x45\xdf\xa3')
        and b'\x42\x82\x84webm' in cabecera
        and b'\x18\x53\x80\x67' in cabecera
        and b'\x16\x54\xae\x6b' in cabecera
        and b'\x1f\x43\xb6\x75' in cabecera
    ):
        raise ValidationError('El archivo no tiene una estructura WebM válida.')


def validar_archivo_imagen(archivo):
    validar_archivo(archivo, extensiones_permitidas={'.jpg', '.jpeg', '.png'})


class EvidenciaForm(forms.ModelForm):
    class Meta:
        model = Evidencia
        fields = ['atencion', 'compromiso', 'descripcion', 'archivo']
        widgets = {
            'atencion': forms.Select(attrs={'class': 'form-select'}),
            'compromiso': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control'}),
            'archivo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/jpeg,image/png'}),
        }

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields['atencion'].queryset = (
            registros_cargables(request, AtencionCiudadana)
            if request is not None
            else AtencionCiudadana.objects.none()
        )
        self.fields['compromiso'].queryset = (
            registros_cargables(request, Compromiso)
            if request is not None
            else Compromiso.objects.none()
        )

    def clean(self):
        cleaned_data = super().clean()
        atencion = cleaned_data.get('atencion')
        compromiso = cleaned_data.get('compromiso')
        if bool(atencion) == bool(compromiso):
            raise ValidationError('Seleccione una actividad o un compromiso.')
        registro = atencion or compromiso
        if self.request is None or not puede_agregar_evidencia(self.request, registro):
            raise ValidationError('No tiene permiso para agregar evidencia a este registro.')
        return cleaned_data

    def clean_archivo(self):
        archivo = self.cleaned_data.get('archivo')
        if archivo:
            validar_archivo_imagen(archivo)
        return archivo


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not isinstance(data, (list, tuple)):
            return [forms.FileField.clean(self, data, initial)]
        if not data and self.required:
            raise ValidationError(self.error_messages['required'], code='required')
        return [forms.FileField.clean(self, archivo, initial) for archivo in data]


class EvidenciaAtencionForm(forms.Form):
    descripcion = forms.CharField(
        label='Descripción (opcional)',
        required=False,
        max_length=240,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    archivos = MultipleFileField(
        label='Archivos (JPG, JPEG, PNG, WebP, MP4 o WebM)',
        widget=MultipleFileInput(
            attrs={
                'class': 'form-control',
                'accept': 'image/jpeg,image/png,image/webp,video/mp4,video/webm',
            }
        ),
    )

    def clean_archivos(self):
        archivos = self.cleaned_data['archivos']
        if not archivos:
            raise ValidationError('Seleccione al menos un archivo.')
        if len(archivos) > 10:
            raise ValidationError('Puede subir hasta 10 archivos por envío.')
        limite_total_mb = settings.EVIDENCIA_MAX_BATCH_MB
        if sum(archivo.size for archivo in archivos) > limite_total_mb * 1024 * 1024:
            raise ValidationError(
                f'El tamaño total supera el máximo permitido de {limite_total_mb} MB por envío.'
            )
        for archivo in archivos:
            validar_archivo(archivo)
        return archivos


class EvidenciaFiltroForm(forms.Form):
    ORIGENES = (
        ('', 'Todos los orígenes'),
        ('atencion', 'Actividad'),
        ('agenda', 'Agenda'),
    )

    q = forms.CharField(
        label='Buscar',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción o identificador'}),
    )
    estado = forms.ChoiceField(
        label='Estado',
        required=False,
        choices=[('', 'Todos los estados')] + list(Evidencia.Estado.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    origen = forms.ChoiceField(
        label='Origen',
        required=False,
        choices=ORIGENES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    subido_por = forms.ModelChoiceField(
        label='Subido por',
        required=False,
        queryset=get_user_model().objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    desde = forms.DateField(
        label='Desde',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    hasta = forms.DateField(
        label='Hasta',
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )

    def __init__(self, *args, subidores=None, **kwargs):
        super().__init__(*args, **kwargs)
        if subidores is not None:
            self.fields['subido_por'].queryset = subidores

    def clean(self):
        cleaned_data = super().clean()
        desde = cleaned_data.get('desde')
        hasta = cleaned_data.get('hasta')
        if desde and hasta and desde > hasta:
            self.add_error('hasta', 'La fecha final debe ser igual o posterior a la inicial.')
        return cleaned_data


class ValidacionEvidenciaForm(forms.Form):
    comentario = forms.CharField(
        label='Comentario',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
