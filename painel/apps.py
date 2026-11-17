from django.apps import AppConfig


class PainelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "painel"
    verbose_name = "Painel dos funcionários"

    def ready(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        def ao_entrar(sender, request, user, **kwargs):
            # Entrou no painel = disponível. Pode trocar para "Ausente" no topo.
            from django.utils import timezone
            get_user_model().objects.filter(pk=user.pk).update(online=True, ultimo_acesso_painel=timezone.now())
            user.online = True

        def ao_sair(sender, request, user, **kwargs):
            if user is not None:
                get_user_model().objects.filter(pk=user.pk).update(online=False)

        user_logged_in.connect(ao_entrar, dispatch_uid="painel_online_ao_entrar")
        user_logged_out.connect(ao_sair, dispatch_uid="painel_online_ao_sair")
