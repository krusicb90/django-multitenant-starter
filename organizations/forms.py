from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

User = get_user_model()

INVITABLE_ROLES = [
    (User.Role.MEMBER, "Member"),
    (User.Role.ADMIN, "Admin"),
    (User.Role.READONLY, "Read-only"),
]


class PasswordPairMixin(forms.Form):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repeat password", widget=forms.PasswordInput)

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two passwords do not match.")
        elif password1:
            try:
                validate_password(password1)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return cleaned


class RegistrationForm(PasswordPairMixin):
    organization_name = forms.CharField(label="Organization", max_length=100)
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField()

    field_order = [
        "organization_name",
        "first_name",
        "last_name",
        "email",
        "password1",
        "password2",
    ]

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email


class InvitationForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=INVITABLE_ROLES)

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("A user with this email address already exists.")
        if self.organization.invitations.filter(email__iexact=email, accepted=False).exists():
            raise forms.ValidationError("This address already has a pending invitation.")
        return email


class InvitationAcceptForm(PasswordPairMixin):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)

    field_order = ["first_name", "last_name", "password1", "password2"]
