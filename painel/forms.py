from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from core.models import CategoriaFAQ, PerguntaFAQ, Ticket, Usuario


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Usuário",
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "ex.: atendente1", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Senha", strip=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Sua senha", "autocomplete": "current-password"}),
    )
    error_messages = {
        "invalid_login": "Usuário ou senha incorretos.",
        "inactive": "Este usuário está desativado. Fale com o supervisor.",
    }


class TicketForm(forms.Form):
    status = forms.ChoiceField(choices=Ticket.Status.choices)
    responsavel = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(is_active=True).order_by("first_name", "username"),
        required=False, empty_label="— ninguém —", label="Responsável",
    )
    resposta = forms.CharField(
        required=False, label="Resposta ao cliente",
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "Escreva a solução. Ela é enviada ao cliente quando o ticket é resolvido."}),
    )
    avisar_cliente = forms.BooleanField(
        required=False, initial=True, label="Avisar o cliente (em andamento / resolvido)",
    )


class CategoriaFAQForm(forms.ModelForm):
    class Meta:
        model = CategoriaFAQ
        fields = ["nome", "ordem"]


class PerguntaFAQForm(forms.ModelForm):
    class Meta:
        model = PerguntaFAQ
        fields = ["categoria", "pergunta", "resposta", "palavras_chave", "ativa"]
        widgets = {
            "resposta": forms.Textarea(attrs={"rows": 6}),
            "palavras_chave": forms.TextInput(attrs={"placeholder": "boleto, pagamento, segunda via"}),
        }


class FuncionarioForm(forms.ModelForm):
    """Cria ou edita um funcionário. Senha só é obrigatória na criação."""

    senha = forms.CharField(
        label="Senha", required=False, strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Mínimo de 8 caracteres. Deixe em branco para não alterar.",
    )

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "apelido", "email", "cargo"]
        labels = {"username": "Usuário (login)", "first_name": "Nome", "last_name": "Sobrenome"}
        help_texts = {"username": "Só letras, números e @/./+/-/_"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.criando = self.instance.pk is None
        if self.criando:
            self.fields["senha"].required = True
            self.fields["senha"].help_text = "Mínimo de 8 caracteres."

    def clean_senha(self):
        senha = self.cleaned_data.get("senha")
        if senha:
            validate_password(senha, self.instance)
        return senha

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get("senha"):
            usuario.set_password(self.cleaned_data["senha"])
        if commit:
            usuario.save()
        return usuario


class RedefinirSenhaForm(forms.Form):
    senha = forms.CharField(label="Nova senha", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirmar = forms.CharField(label="Confirme a nova senha", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def __init__(self, usuario, *args, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def clean(self):
        dados = super().clean()
        if dados.get("senha") and dados.get("senha") != dados.get("confirmar"):
            self.add_error("confirmar", "As senhas não conferem.")
        elif dados.get("senha"):
            try:
                validate_password(dados["senha"], self.usuario)
            except forms.ValidationError as e:
                self.add_error("senha", e)
        return dados
