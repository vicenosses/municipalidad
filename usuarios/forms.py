from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django import forms

from usuarios.models import Delegacion, Perfil


class DelegacionForm(forms.ModelForm):
    class Meta:
        model = Delegacion
        fields = ['nombre', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class UsuarioMunicipalForm(UserCreationForm):
    """Alta de usuario con rol y delegación."""

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
    rol = forms.ChoiceField(
        label='Rol',
        choices=Perfil.Rol.choices,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    delegacion = forms.ModelChoiceField(
        label='Delegación',
        queryset=Delegacion.objects.filter(activa=True),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    cargo = forms.CharField(
        label='Cargo',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
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

    def save(self, commit=True):
        user = super().save(commit=commit)
        perfil, _ = Perfil.objects.get_or_create(usuario=user)
        perfil.rol = self.cleaned_data['rol']
        perfil.delegacion = self.cleaned_data['delegacion']
        perfil.cargo = self.cleaned_data.get('cargo', '')
        perfil.save()
        return user


class PerfilRolForm(forms.ModelForm):
    class Meta:
        model = Perfil
        fields = ['rol', 'delegacion', 'cargo', 'activo']
        widgets = {
            'rol': forms.Select(attrs={'class': 'form-select'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
            'cargo': forms.TextInput(attrs={'class': 'form-control'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
