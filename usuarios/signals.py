from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from usuarios.models import Perfil, Rol


@receiver(post_save, sender=User)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    """Crea un perfil con rol funcionario al dar de alta un usuario."""
    if not created:
        return
    rol = Rol.objects.filter(codigo='funcionario').first()
    Perfil.objects.get_or_create(usuario=instance, defaults={'rol': rol})
