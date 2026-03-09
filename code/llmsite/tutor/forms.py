from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import StudentProfile

def _split_full_name(full_name: str) -> tuple[str, str, str]:
    cleaned = (full_name or "").strip()
    if not cleaned:
        return "", "", ""

    parts = cleaned.split(None, 1)
    first_name = parts[0]
    last_name = parts[1] if len(parts) > 1 else ""
    return cleaned, first_name, last_name

class StudentInitForm(forms.Form):
    studentName = forms.CharField(max_length=100)
    studentSchool = forms.CharField(max_length=200, required=False)
    studentGrade = forms.CharField(max_length=50, required=False)
    studentClasses = forms.CharField(widget=forms.Textarea, required=False)

class MessageForm(forms.Form):
    message = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))

class SignupForm(UserCreationForm):
    full_name = forms.CharField(max_length=200, required=False, help_text="Optional")
    school = forms.CharField(max_length=200, required=False)
    grade = forms.CharField(max_length=50, required=False)
    classes = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields([
            "username",
            "full_name",
            "email",
            "password1",
            "password2",
            "school",
            "grade",
            "classes",
        ])

    def save(self, commit=True):
        user = super().save(commit=False)
        display_name, first_name, last_name = _split_full_name(self.cleaned_data.get("full_name", ""))
        user.first_name = first_name
        user.last_name = last_name
        user.email = self.cleaned_data.get("email", "")

        if commit:
            user.save()
            StudentProfile.objects.create(
                user=user,
                display_name=display_name,
                school=self.cleaned_data.get("school"),
                grade=self.cleaned_data.get("grade"),
                classes=self.cleaned_data.get("classes")
            )
        return user
    
class UploadRagForm(forms.Form):
    title = forms.CharField(max_length=100)
    file = forms.FileField()
