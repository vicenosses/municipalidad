from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from usuarios.models import Perfil


@receiver(post_save, sender=User)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    """Crea un perfil funcionario al dar de alta un usuario."""
    if created:
        Perfil.objects.get_or_create(usuario=instance)
