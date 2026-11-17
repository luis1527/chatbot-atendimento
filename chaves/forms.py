from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import Chave, Sala, Usuario

DATA_HORA = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class UsuarioForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["nome", "matricula", "tipo", "email", "telefone", "ativo"]


class SalaForm(forms.ModelForm):
    class Meta:
        model = Sala
        fields = ["codigo", "nome", "bloco", "andar", "tipo", "capacidade", "ativa"]


class ChaveForm(forms.ModelForm):
    class Meta:
        model = Chave
        fields = ["sala", "codigo", "descricao"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sala"].queryset = Sala.objects.filter(ativa=True)


class EmprestimoForm(forms.Form):
    chave = forms.ModelChoiceField(
        queryset=Chave.objects.none(), label="Chave", empty_label="— escolha uma chave disponível —",
    )
    usuario = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(ativo=True), label="Usuário (quem retira)", empty_label="— escolha o usuário —",
    )
    devolucao_prevista = forms.DateTimeField(
        label="Devolução prevista", widget=DATA_HORA, input_formats=["%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M"],
    )
    observacao = forms.CharField(label="Observação", required=False, max_length=255)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["chave"].queryset = (
            Chave.objects.filter(status=Chave.Status.DISPONIVEL, sala__ativa=True).select_related("sala")
        )
        self.fields["chave"].label_from_instance = lambda c: f"{c.codigo} — {c.sala.nome}"
        if not self.is_bound:
            self.initial.setdefault(
                "devolucao_prevista",
                timezone.localtime(timezone.now() + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M"),
            )

    def clean_devolucao_prevista(self):
        valor = self.cleaned_data["devolucao_prevista"]
        if valor <= timezone.now():
            raise forms.ValidationError("A devolução prevista precisa ser depois de agora.")
        return valor
