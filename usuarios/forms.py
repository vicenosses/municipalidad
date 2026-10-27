from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from django.contrib.auth.models import User

from usuarios.models import Delegacion, Perfil, Rol


class LoginUsuarioCorreoForm(AuthenticationForm):
    username = forms.CharField(
        label='Usuario o correo',
        widget=forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
    )
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Credenciales inválidas o cuenta inactiva.',
        'inactive': 'Esta cuenta está inactiva.',
    }


class SolicitudRecuperacionForm(forms.Form):
    email = forms.EmailField(
        label='Correo asociado',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )


class CodigoRecuperacionForm(forms.Form):
    codigo = forms.CharField(
        label='Código',
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={'class': 'form-control', 'inputmode': 'numeric'}),
    )


class NuevaContrasenaForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['new_password1'].widget.attrs['class'] = 'form-control'
        self.fields['new_password2'].widget.attrs['class'] = 'form-control'


class DelegacionForm(forms.ModelForm):
    class Meta:
        model = Delegacion
        fields = ['nombre', 'direccion', 'comuna', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'comuna': forms.TextInput(attrs={'class': 'form-control'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['nombre'].help_text = 'El código se generará automáticamente al guardar.'


class SolicitudTransferenciaForm(forms.Form):
    usuario = forms.ModelChoiceField(
        label='Usuario',
        queryset=User.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    delegacion_destino = forms.ModelChoiceField(
        label='Delegación de destino',
        queryset=Delegacion.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    motivo = forms.CharField(
        label='Motivo',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )

    def __init__(self, *args, delegacion_origen, **kwargs):
        super().__init__(*args, **kwargs)
        self.delegacion_origen = delegacion_origen
        self.fields['usuario'].queryset = User.objects.filter(
            is_active=True,
            perfil__activo=True,
            perfil__delegacion=delegacion_origen,
            perfil__delegaciones=delegacion_origen,
        ).select_related('perfil').distinct().order_by('last_name', 'first_name', 'username')
        self.fields['delegacion_destino'].queryset = (
            Delegacion.objects.filter(activa=True)
            .exclude(pk=delegacion_origen.pk)
            .order_by('nombre')
        )


class TransferenciaDirectaForm(forms.Form):
    delegacion_destino = forms.ModelChoiceField(
        label='Delegación de destino',
        queryset=Delegacion.objects.none(),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    motivo = forms.CharField(
        label='Observación',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    confirmar_compromisos = forms.BooleanField(
        label='Confirmo continuar sin reasignar los compromisos pendientes.',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def __init__(self, *args, delegacion_origen, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delegacion_destino'].queryset = (
            Delegacion.objects.filter(activa=True)
            .exclude(pk=delegacion_origen.pk)
            .order_by('nombre')
        )


class DecisionTransferenciaForm(forms.Form):
    accion = forms.ChoiceField(
        label='Decisión',
        choices=(('aprobar', 'Aprobar'), ('rechazar', 'Rechazar')),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    observacion_decision = forms.CharField(
        label='Observación',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
    )
    confirmar_compromisos = forms.BooleanField(
        label='Confirmo continuar sin reasignar los compromisos pendientes.',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )


PERMISOS_FLAGS = (
    ('usuarios', 'Usuarios'),
    ('roles', 'Roles'),
    ('delegaciones', 'Delegaciones'),
    ('catalogos', 'Catálogos'),
    ('atenciones', 'Atención ciudadana'),
    ('auditoria', 'Auditoría'),
    ('validar_evidencias', 'Validar evidencias'),
    ('evidencias', 'Evidencias'),
    ('agenda', 'Agenda'),
)


class RolForm(forms.ModelForm):
    class Meta:
        model = Rol
        fields = ['codigo', 'nombre', 'descripcion', 'alcance', 'activo']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'alcance': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actuales = self.instance.permisos if isinstance(self.instance.permisos, dict) else {}
        for clave, etiqueta in PERMISOS_FLAGS:
            self.fields[f'perm_{clave}'] = forms.BooleanField(
                label=f'Permiso: {etiqueta}',
                required=False,
                initial=bool(actuales.get(clave)),
                widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            )

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.permisos = {
            clave: bool(self.cleaned_data.get(f'perm_{clave}'))
            for clave, _etiqueta in PERMISOS_FLAGS
        }
        if commit:
            instance.save()
        return instance


class UsuarioMunicipalForm(UserCreationForm):
    first_name = forms.CharField(
        label='Nombre',
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    last_name = forms.CharField(
        label='Apellido',
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    email = forms.EmailField(
        label='Correo',
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    rol = forms.ModelChoiceField(
        label='Rol',
        queryset=Rol.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    delegaciones = forms.ModelMultipleChoiceField(
        label='Delegaciones autorizadas',
        queryset=Delegacion.objects.filter(activa=True),
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
    )
    cargo = forms.CharField(
        label='Cargo',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    activo = forms.BooleanField(
        label='Activo',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs['class'] = 'form-control'
        self.fields['password2'].widget.attrs['class'] = 'form-control'

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Ya existe un usuario con este correo.')
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        user.email = self.cleaned_data['email']
        user.is_active = self.cleaned_data.get('activo', True)
        user.save()
        perfil, _ = Perfil.objects.get_or_create(usuario=user)
        perfil.rol = self.cleaned_data['rol']
        perfil.cargo = self.cleaned_data.get('cargo', '')
        perfil.activo = self.cleaned_data.get('activo', True)
        delegaciones = list(self.cleaned_data['delegaciones'])
        perfil.delegacion = delegaciones[0] if delegaciones else None
        perfil.save()
        perfil.delegaciones.set(delegaciones)
        return user


class UsuarioEditarForm(forms.ModelForm):
    rol = forms.ModelChoiceField(
        label='Rol',
        queryset=Rol.objects.filter(activo=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    delegaciones = forms.ModelMultipleChoiceField(
        label='Delegaciones autorizadas',
        queryset=Delegacion.objects.filter(activa=True),
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5}),
    )
    cargo = forms.CharField(
        label='Cargo',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    activo = forms.BooleanField(
        label='Activo',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        labels = {
            'username': 'Usuario',
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Correo',
        }
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        perfil = getattr(self.instance, 'perfil', None)
        if perfil:
            self.fields['rol'].initial = perfil.rol_id
            self.fields['delegaciones'].initial = perfil.delegaciones.values_list('id', flat=True)
            self.fields['cargo'].initial = perfil.cargo
            self.fields['activo'].initial = perfil.activo and self.instance.is_active

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe un usuario con este correo.')
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        activo = self.cleaned_data.get('activo', True)
        user.is_active = activo
        user.save()
        perfil, _ = Perfil.objects.get_or_create(usuario=user)
        perfil.rol = self.cleaned_data['rol']
        perfil.cargo = self.cleaned_data.get('cargo', '')
        perfil.activo = activo
        delegaciones = list(self.cleaned_data['delegaciones'])
        ids = {d.pk for d in delegaciones}
        if perfil.delegacion_id in ids:
            pass
        else:
            perfil.delegacion = delegaciones[0] if delegaciones else None
        perfil.save()
        perfil.delegaciones.set(delegaciones)
        return user
